#!/usr/bin/env python
from pathlib import Path

import os

from pydantic import BaseModel

from crewai.flow import Flow, listen, start
from ag_ui_crewai.sdk import copilotkit_stream, CopilotKitState

from ms_tb01.crews.crew import kickoff_content_crew
from ms_tb01.kafka.kafka_producer import producer, delivery_report

class ContentState(BaseModel):
    topic: str = ""
    outline: str = ""
    draft: str = ""
    final_post: str = ""



class ContentFlow(Flow[ContentState]):

    @start()
    def plan_content(self, crewai_trigger_payload: dict = None):
        print("Planning content")
        print(os.getenv("DEEPSEEK_API_KEY"))

        if crewai_trigger_payload:
            self.state.topic = crewai_trigger_payload.get("topic", "AI Agents")
            print(f"Using trigger payload: {crewai_trigger_payload}")
        else:
            self.state.topic = "AI Agents"

        print(f"Topic: {self.state.topic}")

    @listen(plan_content)
    def generate_content(self):
        print(f"Generating content on: {self.state.topic}")
        result = kickoff_content_crew({"topic": self.state.topic})
        print("Content generated")
        self.state.final_post = result.raw

    @listen(generate_content)
    def save_content(self):
        print("Saving content")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        with open(output_dir / "post.md", "w") as f:
            f.write(self.state.final_post)
        print("Post saved to output/post.md")

        producer.produce(
        'test',
        key='crewai',
        value=self.state.final_post,
        callback=delivery_report,
        )
        producer.flush()

        print("Post saved and published to Kafka")


def kickoff():
    content_flow = ContentFlow()
    content_flow.kickoff()


def plot():
    content_flow = ContentFlow()
    content_flow.plot()


def run_with_trigger():
    """
    Run the flow with trigger payload.
    """
    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    content_flow = ContentFlow()

    try:
        result = content_flow.kickoff({"crewai_trigger_payload": trigger_payload})
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")


if __name__ == "__main__":
    kickoff()
