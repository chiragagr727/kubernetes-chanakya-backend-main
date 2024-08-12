import json
import os
from channels.generic.websocket import AsyncWebsocketConsumer
from premium_features.services.openai_service import TogetherAIService
from premium_features.services.transcription_service import TranscriptionService
from premium_features.services.tts_service import TTSService
from premium_features.services.tts_embedding_data import speaker_embedding, gpt_cond_latent


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

        # Initialize services
        self.openai_service = TogetherAIService(api_key=os.environ.get("TOGETHER_API_TOKEN"))
        self.transcription_service = TranscriptionService(api_key=os.environ.get("GROQ_API_TOKEN"))
        self.tts_service = TTSService(speaker_embedding=speaker_embedding, gpt_cond_latent=gpt_cond_latent)

        await self.openai_service.setup()
        await self.tts_service.setup()

    async def disconnect(self, close_code):
        await self.openai_service.close()
        await self.tts_service.close()

    async def receive(self, bytes_data):
        try:
            if bytes_data:
                async for response_data in self._answer_from_text(bytes_data):
                    if isinstance(response_data, bytes):
                        await self.send(bytes_data=response_data)
                    else:
                        await self.send(text_data=response_data)
            else:
                await self.send(text_data=json.dumps({"error": "Empty message received"}))
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON format"}))
        except Exception as e:
            await self.send(text_data=json.dumps({"error": str(e)}))

    async def _answer_from_text(self, audio_bytes):
        text = await self.transcription_service.transcribe_audio_file(audio_bytes)
        if not text or "Error" in text:
            yield json.dumps({"error": "Failed to transcribe audio"})
            return

        content = [
            {'role': 'system', 'content': 'You are a funny bot created by neurobridge. Your interface with users '
                                          'will be voice. You should use short and concise responses, '
                                          'and avoid usage of unpronounceable punctuation.'},
            {'role': 'user', 'content': text}
        ]

        try:
            async for combined_text in self.openai_service.get_chat_response(content):
                audio_bytes = await self.tts_service.generate_tts_audio(combined_text)
                if audio_bytes:
                    yield audio_bytes

        except Exception as e:
            yield json.dumps({"error": f"Error getting chat response: {str(e)}"})

        yield json.dumps({"message": "Response processing complete"})
