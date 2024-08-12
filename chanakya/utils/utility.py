import os
import base64
import requests
from django.core.cache import cache
from chanakya.models.prompts_model import PromptsModel
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from chanakya.utils import sentry
import logging
from chanakya.utils import custom_exception
from chanakya.models.conversation import ConversationModel, MessageModel
from chanakya.enums.role_enum import RoleEnum
from chanakya.utils.prompt_builder import PromptBuilder
from chanakya.tasks.title_generator_task import generate_conversation_title

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_NAME = os.getenv("DEFAULT_PROMPT_NAME")
DEFAULT_IOS_PROMPT_NAME = os.getenv("DEFAULT_IOS_PROMPT_NAME")


def check_rate_limit_of_conversation(user, rate_limit=40, time_limit=180):
    cache_key = f"user_{user.id}_message_count"

    message_count = cache.get(cache_key, 0)

    if message_count >= rate_limit:
        raise custom_exception.RateLimitExceed(
            f"Rate limit exceeded: Only {rate_limit} messages allowed per {time_limit} minute(s).")

    cache.set(cache_key, message_count + 1, time_limit + 60)


def get_prompt_instance(model_name=None, is_ios=False, cache_timeout=60 * 60 * 720):
    if model_name is None:
        # model_name = DEFAULT_IOS_PROMPT_NAME
        if is_ios:
            model_name = DEFAULT_IOS_PROMPT_NAME
        else:
            model_name = DEFAULT_PROMPT_NAME
    prompt_instance = cache.get(model_name)
    if prompt_instance is None:
        try:
            prompt_instance = PromptsModel.objects.get(name=model_name)
            cache.set(model_name, prompt_instance, timeout=cache_timeout)
        except PromptsModel.DoesNotExist:
            raise custom_exception.InvalidData("Prompt Model Not Found")
        except Exception as e:
            raise custom_exception.InvalidData("Error retrieving Prompt Model")
    return prompt_instance


def build_prompt_and_get_conversation_history(conversation, query, prompt_builder):
    try:
        messages = MessageModel.objects.filter(conversation=conversation).order_by("updated")[:4]
    except Exception as e:
        messages = ""
    conversation_history = [{"role": msg.role, "content": msg.content} for msg in messages]
    # logger.debug(f"in chanakya_chat.build_prompt() conversation history:\n{conversation_history}")
    # logger.info(f"*************************************")
    return prompt_builder.build_prompt(conversation_history=conversation_history,
                                       user_question=query), conversation_history


class SendRequestForTogetherStreaming:
    def __init__(self, model, temperature, top_p, top_k, max_tokens, repetition_penalty, stop):
        self._model = model
        self._temperature = temperature
        self._top_p = top_p
        self._top_k = top_k
        self._max_tokens = max_tokens
        self._repetition_penalty = repetition_penalty
        self._stop = stop

    def __call__(self, together_api_token, prompt, url):
        payload = {
            "model": self._model,
            "prompt": str(prompt),
            "temperature": self._temperature,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "max_tokens": self._max_tokens,
            "repetition_penalty": self._repetition_penalty,
            "stream": True,
            "stream_tokens": True,
            "type": "chat",
            "stop": self._stop,
            # "safety_model": "meta-llama/Meta-Llama-Guard-3-8B",
        }
        headers = {
            "Authorization": f"Bearer {together_api_token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json"
        }
        try:
            upstream_response = requests.post(url, json=payload, headers=headers, stream=True)
            upstream_response.raise_for_status()
            return upstream_response
        except requests.exceptions.HTTPError as http_err:
            logger.debug(f"payload of together api \n {payload}")
            sentry.capture_error(message="http error while sending request", user_email="temporary_chat",
                                 exception=http_err)
            raise custom_exception.InvalidRequest("401 Client Error")
        except requests.exceptions.RequestException as req_err:
            logger.debug(f"payload of together api \n {payload}")
            sentry.capture_error(message="http error while sending request", user_email="temporary_chat",
                                 exception=req_err)
            raise custom_exception.InvalidRequest("404 Request Error")


class EncryptionDecryption:

    def __init__(self, fernet_key):
        self.fernet_key = fernet_key

    def decrypt(self, hash_prompt):
        try:
            key = base64.b64decode(self.fernet_key)
            encrypted_api_key = base64.b64decode(hash_prompt)
            cipher = AES.new(key, AES.MODE_ECB)
            decrypted_api_key = unpad(cipher.decrypt(encrypted_api_key), AES.block_size).decode()
            return decrypted_api_key
        except Exception as e:
            raise custom_exception.InvalidRequest(f"Failed to decrypt: {e}")


def build_prompt_for_conversation(is_ios, conversation, question):
    try:
        prompt_instance = get_prompt_instance(model_name=None, is_ios=is_ios)
        prompt_builder = PromptBuilder(start_token=prompt_instance.start_token,
                                       end_token=prompt_instance.end_token,
                                       user_token=prompt_instance.user_token,
                                       assistant_token=prompt_instance.assistant_token,
                                       eot_token=prompt_instance.eot_token,
                                       system_message=prompt_instance.system_message,
                                       begin_of_text_token=prompt_instance.begin_of_text_token,
                                       system_token=prompt_instance.system_token
                                       )
        prompt, conversation_history = build_prompt_and_get_conversation_history(conversation, query=question,
                                                                                 prompt_builder=prompt_builder)
        logger.debug(f"prompt history of chanakya search:\n {prompt}")
        logger.debug(f"conversation history of chanakya search:\n {conversation_history}")
        if conversation:
            MessageModel.objects.create(conversation=conversation, content=question, role=RoleEnum.USER.value)
        return prompt, conversation_history
    except Exception as e:
        logger.error(e)
        raise custom_exception.InvalidRequest(f"Failed to build Prompt: {e}]")


def update_message(conversation, conversation_history, complete_text, ):
    MessageModel.objects.create(conversation=conversation, content=complete_text,
                                role=RoleEnum.ASSISTANT.value)
    if not conversation_history:
        messages = MessageModel.objects.filter(conversation=conversation)
        conversation_history_1 = [{"role": msg.role, "content": msg.content} for msg in messages]
        generate_conversation_title.delay(conversation.id, conversation_history_1)


def get_conversation_details(conversation_id, user_info):
    conversation_cache_id = f"conversation_{conversation_id}"
    conversation = cache.get(conversation_cache_id)

    if conversation is None:
        try:
            conversation = ConversationModel.objects.get(id=conversation_id, user=user_info)
            cache.set(conversation_cache_id, conversation)
        except ConversationModel.DoesNotExist:
            raise custom_exception.InvalidData("Provided Conversation is not correct")
        except Exception as e:
            raise custom_exception.InvalidData("Provided Conversation is not correct")
    if conversation is None:
        raise custom_exception.InvalidData("Conversation Not Found")
    return conversation
