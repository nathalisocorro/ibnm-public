# src/latest_ai_flow/crews/content_crew/content_crew.py
from crewai import Crew, Process
from ms_tb01.crews.agents.agents import translator
from ms_tb01.crews.tasks.tasks import translator_task

# API path (use one or the other, not both)


def kickoff_content_crew(inputs: dict):
  crew = Crew(agents=[translator], tasks=[translator_task], process=Process.sequential)
  return crew.kickoff(inputs=inputs)