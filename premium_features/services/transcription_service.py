import tempfile
import time
from groq import Groq


class TranscriptionService:
    def __init__(self, api_key):
        self.client = Groq(api_key=api_key)

    async def transcribe_audio_file(self, audio_bytes):
        try:
            start_time = time.time()

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio_file:
                temp_audio_file.write(audio_bytes)
            filename = temp_audio_file.name
            with open(filename, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(filename, file.read()),
                    model="whisper-large-v3",
                    prompt="Specify context or spelling",
                    response_format="json",
                    language="en",
                    temperature=0.0
                )
            text = transcription.text

            end_time = time.time()
            duration = end_time - start_time

            print("transcription_text:", text)
            print("Time taken for transcription:", duration, "seconds")
            return text

        except Exception as e:
            return f"Error transcribing audio file: {str(e)}"
