"""
This eval takes clones a repository locally and then has an agent encode the repository into forgetful,
a knowledge base that builds a semantic graph of agent observation and memories.

The eval then proceeds to have the agent, answer questions about the repo without access to the code
and just the forgetful knowledge base
"""
from src.helpers.file_helper import read_eval_fixture, read_questions

ENCODING_PROMPT = ""
REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""
QUESTIONS= ""
ANSWERS = ""

class EncodeRepoForgetful:

    arrange_embedded_values = {
        "REPO_URL": "https://github.com/fastapi/typer",
        "REPO_REF": "0.26.7",
        "REPO_DIR": "/workspace/typer",
        "ENCODING_PROMPT": read_eval_fixture(__file__, "encoding_prompt.md"),
    }
    act_embedded_values = {
        "QUESTIONS":  read_questions(__file__, False)
    }
    score_embedded_values = {
        "ANSWERS": read_questions(__file__, True)
    }

    async def arrange(self) -> None:
        import os 
        import subprocess
        import time
        from agent_shell.shell import AgentShell 
        from agent_shell.models.agent import AgentType, MCPServerSpec, MCPServerType

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

        timeout = 5 * 60
        start_timer = time.time() 
        timer = 0 
        mcp_servers = []  
        while timer < timeout:
            try:
                mcp_servers = await shell.list_mcp_servers()
            except Exception: 
                pass 
            if mcp_servers:
                break 
            time.sleep(2)
            timer = time.time() - start_timer 

        if not mcp_servers:
            raise RuntimeError(f"forgetful MCP server failed to initialise withing {timeout}s - aborting eval")

        print(mcp_servers)
        print("forgetful initialised")

        print("cloning github repo")
        # Private repos: GH_TOKEN (injected by the harness when configured) lets gh
        # register itself as git's credential helper, so the HTTPS clone below
        # authenticates. No-op for public repos / when unset — the clone still runs
        # anonymously, and gh is never invoked with an empty token.
        if os.environ.get("GH_TOKEN"):
            subprocess.run(["gh", "auth", "setup-git"], check=True)

        subprocess.run(
                ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
                 "--depth", "1", "--branch", REPO_REF, REPO_URL, REPO_DIR],
                check=True,
              )

        print("encoding repository into forgetful")
        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
        response = await shell.execute(
            cwd=REPO_DIR,
            prompt=ENCODING_PROMPT,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

        print("removing repo from file system")
        subprocess.run(["rm", "-rf", REPO_DIR], check=True)
        print("repo removed")

    async def act(self) -> None:
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        os.makedirs("/workspace", exist_ok=True)
        with open("/workspace/answers.json", "w") as f:
            f.write(QUESTIONS)

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))

        print("calling agent")
        response = await shell.execute(
            cwd="/workspace",
            prompt="""
            The file in /workspace/answers.json contains a list of questions, each with choices and 
            an empty "answer" field. For each question, choose the correct option and write the single
            upper case letter (A, B, C, or D) into its "answer" field.

            Use ONLY information from the forgetful memory system - do not guess. Edit the file in 
            place, keep it valid JSON change nothing else
            """,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
            disallowed_tools=["bash", "web_search", "web_fetch"],
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import os
        import json

        if not os.path.exists("/workspace/answers.json"):
            print("EVAL_SCORE=0.0") 
            return 
        
        agent_answers = {}
        try:
            with open("/workspace/answers.json", "r") as f:
                agent_answers = json.loads(f.read())
            agent_answers_dict = {a["id"]: a["answer"] for a in agent_answers["questions"]}
        except(OSError, ValueError, KeyError, TypeError):
            print("EVAL_SCORE=0.0")
            return

        correct = 0 
        try: 
            scaffold = json.loads(ANSWERS)

            for q in scaffold["questions"]:
                answer = str(agent_answers_dict.get(q["id"], "")).strip().upper()
                if answer == q["answer"].strip().upper():
                    correct += 1 

            score = correct / len(scaffold["questions"]) 
            print(f"EVAL_SCORE={score:.4f}")
        except json.JSONDecodeError as e:
            raise RuntimeError("Invalid embedded ANSWERS JSON") from e
        except Exception as e:
            raise RuntimeError("Error scoring forgetful encode eval") from e

        
    
