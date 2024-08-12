from langchain_google_community import GoogleSearchAPIWrapper
from langchain_core.tools import Tool
from typing_extensions import TypedDict
import os
from premium_features.views import gs_prompt
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from rest_framework import viewsets
from chanakya.utils import custom_exception
from langchain_together import ChatTogether
from chanakya.utils import mixpanel, utility
from chanakya.serializer.chanakya_chat_serializer import ChanakyaSearchRequestSerializer
from chanakya.utils.prompt_builder import PromptBuilder, GoogleSearchPromptBuilder
from django.http import StreamingHttpResponse
import json
import logging

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    question: str
    generation: str
    search_query: str
    context: str


class ChanakyaGoogleSearchEngine(viewsets.ViewSet):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

    def create(self, request):
        user_info = request.META.get('user', None)
        auth_user_id = request.META.get("sub", None)
        if not user_info:
            raise custom_exception.DataNotFound("User not found")

        serializer = ChanakyaSearchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            error = next(iter(serializer.errors.values()))[0]
            raise custom_exception.InvalidData(error)

        serialized_data = serializer.validated_data
        question = serialized_data.get('query')
        conversation = serialized_data.get('conversation_id', None)
        is_ios = serialized_data.get("is_ios", True)

        logger.info("************** Chanakya web search route***********************")

        conversation = utility.get_conversation_details(conversation, user_info)

        request_id = getattr(request, 'request_id', None)
        unique_id = f'{request_id}-chanakya'

        def response_generator(complete_text=""):
            try:
                yield f"data: {json.dumps({'id': unique_id, 'status': 'Processing'})}\n\n"

                route_question = self.route_and_generate_query(question)
                route_step = route_question.get("route_step")
                is_health_related = route_question.get("is_health_related")

                if is_health_related:
                    health_disclaimer = (
                        "\n\nImportant: This information is for general educational purposes only and should not be considered as medical advice. "
                        "Always consult with a qualified healthcare professional for personalized medical advice.\n\n"
                    )
                    response_data = {'id': unique_id, "response": health_disclaimer}
                    yield f"data: {json.dumps(response_data)}\n\n"

                prompt, conversation_history = utility.build_prompt_for_conversation(is_ios, conversation, question)

                if route_step == "websearch":
                    yield f"data: {json.dumps({'id': unique_id, 'step': True})}\n\n"
                    context = self.search_tool.run(question)
                    logger.info(f"context: {context}", context)

                    if is_health_related:
                        context = [
                            result for result in context
                            if
                            'link' in result and any(domain in result['link'] for domain in self.TRUSTED_HEALTH_SOURCES)
                        ]
                        logger.info(f"context after health check: {context}", context)

                    links = [result['link'] for result in context]
                    generation_with_links = "\n".join(f"{idx + 1}. [{link}]({link})" for idx, link in enumerate(links))
                    sources = {'id': unique_id, 'sources': generation_with_links}
                    yield f"data: {json.dumps(sources)}\n\n"

                    for gen in self.search_based_chain.stream({"context": context, "question": prompt}):
                        complete_text += gen
                        response_data = {'id': unique_id, "response": gen}
                        logger.debug(f"response: {response_data}")
                        yield f"data: {json.dumps(response_data)}\n\n"
                    mixpanel._chat_with_google_search(auth_user_id)

                elif route_step == "generate_without_search":
                    yield f"data: {json.dumps({'id': unique_id, 'step': False})}\n\n"
                    context = ""

                    for gen in self.normal_chain.stream({"context": context, "question": prompt}):
                        complete_text += gen
                        response_data = {'id': unique_id, "response": gen}
                        logger.debug(f"response: {response_data}")
                        yield f"data: {json.dumps(response_data)}\n\n"
                    mixpanel._chat_without_web_search(auth_user_id)

                else:
                    yield f"data: {json.dumps({'id': unique_id, 'step': None})}\n\n"

                yield f"data: {json.dumps({'id': unique_id, 'status': 'End'})}\n\n"
                utility.update_message(conversation, conversation_history, complete_text)

            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        try:
            response = StreamingHttpResponse(response_generator())
            response['Cache-Control'] = 'no-cache'
            response['Content-Type'] = 'text/event-stream'
            response['X-Accel-Buffering'] = 'no'

            return response

        except Exception as e:
            raise custom_exception.InvalidRequest(str(e))

    def route_question(self, state):
        logger.info("Step: Routing Query")
        question = state['question']
        output = self.question_router.invoke({"question": question})
        if output['choice'] == "web_search":
            logger.info("Step: Routing Query to Web Search")
            return "websearch"
        elif output['choice'] == 'generate':
            logger.info("Step: Routing Query to Generation without Web Search")
            return "generate_without_search"

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
