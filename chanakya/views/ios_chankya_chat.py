import json
import logging
import os
import time
from langchain_google_community import GoogleSearchAPIWrapper
from langchain_core.tools import Tool
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from typing_extensions import TypedDict
from premium_features.views import gs_prompt
from chanakya.utils import custom_exception, mixpanel, utility
from chanakya.utils.prompt_builder import GoogleSearchPromptBuilder
from langchain_together import ChatTogether

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    question: str
    generation: str
    search_query: str
    context: str


class ChanakyaIosSearchEngine:
    def __init__(self, request_id, question, prompt, conversation, conversation_history, auth_user_id):
        self.chat = ChatTogether(
            model="meta-llama/Llama-3-70b-chat-hf",
            together_api_key=os.environ.get("TOGETHER_API_TOKEN")
        )

        self.search = GoogleSearchAPIWrapper()
        self.search_tool = Tool(
            name="google_search",
            description="Search Google for recent results.",
            func=self.top5_results,
        )

        self.search_based_prompt = gs_prompt.search_based_prompt
        self.normal_prompt = gs_prompt.normal_prompt
        self.search_based_chain = self.search_based_prompt | self.chat | StrOutputParser()
        self.normal_chain = self.normal_prompt | self.chat | StrOutputParser()

        self.prompt_instance = GoogleSearchPromptBuilder()
        self.router_prompt = self.prompt_instance.build_prompt_for_router(model_name="chanakya-v1-router")
        self.query_prompt = self.prompt_instance.build_prompt_for_query_prompt(mode_name="chanakya-v1-query")
        self.question_router = self.router_prompt | self.chat | JsonOutputParser()
        self.query_chain = self.query_prompt | self.chat | JsonOutputParser()
        self.TRUSTED_HEALTH_SOURCES = ["nih.gov", "who.int", "cdc.gov", "nhs.uk", "mohfw.gov.in", "mayoclinic.org",
                                       "healthline.com"]
        self.request_id = request_id
        self.question = question
        self.prompt = prompt
        self.conversation = conversation
        self.conversation_history = conversation_history
        self.auth_user_id = auth_user_id

    def generate_response(self, unique_id, timestamp, text, model='', sources=None, finish_reason=None):
        """Helper function to generate the response structure."""
        return {
            'id': unique_id,
            'object': 'chat.completion.chunk',
            'created': timestamp,
            'choices': [
                {
                    'index': 0,
                    'text': text,
                    'sources': sources if sources is not None else [],
                    'logprobs': None,
                    'finish_reason': finish_reason,
                    'seed': None,
                    'delta': {}
                }
            ],
            'model': model,
            'usage': None
        }

    def send_request(self, complete_text=""):
        unique_id = f'{self.request_id}-chanakya'
        timestamp = int(time.time())

        try:
            route_question = self.route_and_generate_query(self.question)
            route_step = route_question.get("route_step")
            is_health_related = route_question.get("is_health_related")

            if is_health_related:
                health_disclaimer = (
                    "\n\nImportant: This information is for general educational purposes only and should not be considered as medical advice. "
                    "Always consult with a qualified healthcare professional for personalized medical advice.\n\n"
                )
                health_response_data = self.generate_response(unique_id, timestamp, health_disclaimer)
                yield f"data: {json.dumps(health_response_data)}\n\n"

            if route_step == "websearch":
                context = self.search_tool.run(self.question)
                logger.info(f"context: {context}")

                if is_health_related:
                    context = [
                        result for result in context
                        if 'link' in result and any(domain in result['link'] for domain in self.TRUSTED_HEALTH_SOURCES)
                    ]
                    logger.info(f"context after health check: {context}")

                links = [result['link'] for result in context]
                sources = self.generate_response(unique_id=unique_id, timestamp=timestamp,
                                                 sources=links, text='')
                yield f"data: {json.dumps(sources)}\n\n"

                for gen in self.search_based_chain.stream({"context": context, "question": self.prompt}):
                    complete_text += gen
                    response_data = self.generate_response(unique_id, timestamp, gen)
                    logger.debug(f"response: {response_data}")
                    yield f"data: {json.dumps(response_data)}\n\n"

                mixpanel._chat_with_google_search(self.auth_user_id)

            elif route_step == "generate_without_search":
                context = ""
                for gen in self.normal_chain.stream({"context": context, "question": self.prompt}):
                    complete_text += gen
                    response_data = self.generate_response(unique_id, timestamp, gen)
                    logger.debug(f"response: {response_data}")
                    yield f"data: {json.dumps(response_data)}\n\n"

                mixpanel._chat_without_web_search(self.auth_user_id)

            yield "data: [DONE]\n\n"
            utility.update_message(self.conversation, self.conversation_history, complete_text)

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    def top5_results(self, query):
        return self.search.results(query, 5)

    def route_and_generate_query(self, question):
        logger.debug(f"Routing Query for iOS: {question}")
        prompt_and_query = self.prompt_instance.prompt_for_ios(mode_name="chanakya-v1-router-generate-query")
        router_and_query_chain = prompt_and_query | self.chat | JsonOutputParser()
        logger.debug("Routing Query for Web Search")
        try:
            output = router_and_query_chain.invoke({
                "question": question,
                "trusted_health_sources": ", ".join(self.TRUSTED_HEALTH_SOURCES)
            })

            logger.debug(f"Output: {output}")
            logger.debug(f"Routing Decision: {output['reasoning']}")

            if output['needs_search']:
                if output['is_health_related']:
                    search_query = f"site:({' OR site:'.join(self.TRUSTED_HEALTH_SOURCES)}) {output['search_query']}"
                else:
                    search_query = output['search_query']
                logger.debug(f"Routing Query to Web Search with query: {search_query}")
                return {"search_query": search_query, "is_health_related": output['is_health_related'],
                        "route_step": "websearch"}
            else:
                logger.debug("Routing Query to Generation without Web Search")
                return {"context": None, "is_health_related": output['is_health_related'],
                        "route_step": "generate_without_search"}
        except Exception as e:
            logger.error(f"Error in routing: {e}")
            raise custom_exception.InvalidRequest("Failed to route the query")
