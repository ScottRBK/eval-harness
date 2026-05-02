
class EncodeRepoForgetful:

    def arrange(self) -> None:
        print("just testing at this point")

    def act(self) -> None:
        print("just testing at this point")
        import asyncio, os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        async def _run(): 
            shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
            return await shell.execute(
            cwd="/workspace",
            prompt="What model and harness are you?",
            allowed_tools=["Read", "Glob", "Grep"],
            model=os.environ["AGENT_MODEL"],
            )

        response = asyncio.run(_run())
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    def score(self) -> None:
        print("0")
