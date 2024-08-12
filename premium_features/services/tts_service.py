import aiohttp


class TTSService:
    def __init__(self, speaker_embedding, gpt_cond_latent):
        self.speaker_embedding = speaker_embedding
        self.gpt_cond_latent = gpt_cond_latent
        self.http_session = None

    async def setup(self):
        self.http_session = aiohttp.ClientSession()

    async def close(self):
        if self.http_session:
            await self.http_session.close()

    async def generate_tts_audio(self, text):
        audio_session_data = {
            "speaker_embedding": self.speaker_embedding,
            "gpt_cond_latent": self.gpt_cond_latent,
            "text": text,
            "language": "en"
        }

        headers = {
            "Content-Type": "application/json"
        }

        async with self.http_session.post("http://164.52.217.88:8000/tts", json=audio_session_data,
                                          headers=headers) as response:
            if response.status == 200:
                return await response.read()
            else:
                return None
