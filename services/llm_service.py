import asyncio
import json
import logging
from typing import Any, Dict, Optional
import ollama

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, model: str = "llama3.2"):
        """
        Initializes the LLM Service wrapper.
        Default model can be configured to whatever is running locally.
        """
        self.model = model
        self.queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self.client = ollama.AsyncClient()
        
    async def start(self):
        """Starts the background worker that processes LLM requests sequentially."""
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._process_queue())
            logger.info("LLM background worker started (Concurrency: 1).")

    async def stop(self):
        """Stops the background worker."""
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
            logger.info("LLM background worker stopped.")

    async def _process_queue(self):
        """Processes LLM tasks one by one to prevent VRAM OOM errors."""
        while True:
            future, prompt, schema = await self.queue.get()
            try:
                result = await self._call_llm(prompt, schema)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self.queue.task_done()

    async def generate_structured_output(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enqueues an LLM generation task and awaits its completion.
        """
        if not self._worker_task:
            await self.start()
            
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((future, prompt, schema))
        return await future

    async def _call_llm(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Actual LLM API call, enforcing strict JSON Schema using native structured output.
        Wrapped with backoff retries.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.client.generate(
                    model=self.model,
                    prompt=prompt,
                    format=schema,
                    stream=False
                )
                
                # The response from Ollama should be JSON string conforming to the schema
                return json.loads(response['response'])
                
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error("Max retries reached for LLM call.")
                    raise
                await asyncio.sleep(2 ** attempt) # Exponential backoff
