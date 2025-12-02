from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List


@CrewBase
class CrewaiCodecrew():
    """CrewaiCodecrew crew"""

    agents: List[BaseAgent]
    tasks: List[Task]


    @agent
    def engineering_lead(self) -> Agent:
        """Engineering Lead"""
        return Agent(
            config=self.agents_config["engineering_lead"],
            verbose=True,
        )

    @agent
    def backend_engineer(self) -> Agent:
        """Backend Engineer"""
        return Agent(
            config=self.agents_config["backend_engineer"],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",
            max_execution_time=240,
            max_retries=5,
        )
    
    @agent
    def frontend_engineer(self) -> Agent:
        """Frontend Engineer"""
        return Agent(
            config=self.agents_config["frontend_engineer"],
            verbose=True,
        )
    
    @agent
    def test_engineer(self) -> Agent:
        """Test Engineer"""
        return Agent(
            config=self.agents_config["test_engineer"],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",
            max_execution_time=240,
            max_retries=5,
        )

    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task'],
        )

    @task
    def code_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_task'],
        )

    @task
    def frontend_task(self) -> Task:
        return Task(
            config=self.tasks_config["frontend_task"]
        )

    @task
    def test_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_task'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the CrewaiCodecrew crew"""

        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )