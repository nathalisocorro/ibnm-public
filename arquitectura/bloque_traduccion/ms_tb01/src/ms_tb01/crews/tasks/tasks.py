from crewai import Task
from ms_tb01.crews.agents.agents import translator

translator_task = Task(
    description="""Transform the given intention {topic} into a structured JSON object 
                   with the following fields:
                   - intent_id: A unique identifier for the intention.
                   - objective: A concise statement of the goal or purpose.
                   - parameters: Key-value pairs relevant to the intention.""",
    expected_output="""{
        "intent_id": "<unique_id>",
        "objective": "<concise_goal>",
        "parameters": {
            "param1": "value1",
            "param2": "value2"
        }
    }""",
    agent=translator,
)