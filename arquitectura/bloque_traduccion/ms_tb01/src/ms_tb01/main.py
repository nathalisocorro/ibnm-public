from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from ms_tb01.flows.flow import ContentFlow

app = FastAPI(title="CrewAI Agent Server")

class TriggerRequest(BaseModel):
    topic: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/trigger-content")
async def trigger_content(request: TriggerRequest, background_tasks: BackgroundTasks):
    payload = {"crewai_trigger_payload": {"topic": request.topic}}
    background_tasks.add_task(ContentFlow().kickoff, payload)
    return {"status": "started", "topic": request.topic}