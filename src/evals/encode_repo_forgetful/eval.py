from src.helpers.file_helper import read_eval_fixture

ENCODING_PROMPT = ""

class EncodeRepoForgetful:

    arrange_embedded_values = {
    }
    act_embedded_values = {
        "ENCODING_PROMPT": read_eval_fixture(__file__, "encoding_prompt.md")
    }
    score_embedded_values = {}


    async def arrange(self) -> None:
        import os 
        import subprocess
        import time
        from agent_shell.shell import AgentShell 
        from agent_shell.models.agent import AgentType, MCPServerSpec, MCPServerType
        #TODO: Configure MCP for Forgetful
        # print(subprocess.run(["uv", "tool", "install", "forgetful-ai", ], 
                             # capture_output=True, text=True,check=True).stdout[:500])
        print("initiating forgetful server mcp")
        subprocess.run(["uvx", "forgetful-ai"], capture_output=True, text=True)
        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
        forgetful_mcp = MCPServerSpec(
            name="forgetful",
            type=MCPServerType.STDIO,
            command="uvx",
            args=["forgetful-ai"],
        )
        await shell.add_mcp_server(forgetful_mcp)

        # pause here for a bit to allow the fastembed model to download
        time.sleep(60)

        print("forgetful initalised")
        print(subprocess.run(["opencode", "mcp", "list"], capture_output=True, text=True).stdout)

        #TODO: Clone the repo that we want to encode
        print("cloning github repo")

        #TODO: Encode the repo that we want to encode


    async def act(self) -> None:
        print("just testing at this point")
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
        response = await shell.execute(
            cwd="/workspace",
            prompt=ENCODING_PROMPT,
            allowed_tools=["Read", "Glob", "Grep"],
            model=os.environ["AGENT_MODEL"],
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        print("0")
