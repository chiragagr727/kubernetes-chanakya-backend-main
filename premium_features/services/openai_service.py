import aiohttp
import json
import ssl
import certifi


class TogetherAIService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.http_session = None
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def setup(self):
        self.http_session = aiohttp.ClientSession()

    async def close(self):
        if self.http_session:
            await self.http_session.close()

    async def get_chat_response(self, messages):
        payload = {
            "model": "meta-llama/Llama-3-70b-chat-hf",
            "messages": messages,
            "stream": True
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        collected_texts = []

        async with self.http_session.post("https://api.together.xyz/v1/chat/completions", json=payload, headers=headers,
                                          ssl=self.ssl_context, timeout=60) as response:
            async for chunk in response.content.iter_chunked(4096):
                try:
                    if chunk:
                        json_data = chunk.decode('utf-8').split('\n')
                        for line in json_data:
                            if line.startswith('data: '):
                                line_data = line[6:].strip()
                                if line_data:
                                    response = json.loads(line_data)
                                    if 'choices' in response and response['choices']:
                                        text_value = response['choices'][0]['text']
                                        collected_texts.append(text_value)

                                        if len(collected_texts) >= 15:
                                            combined_text = ''.join(collected_texts)
                                            collected_texts = []
                                            yield combined_text
                except Exception as e:
                    continue

        if collected_texts:
            combined_text = ''.join(collected_texts)
            yield combined_text
