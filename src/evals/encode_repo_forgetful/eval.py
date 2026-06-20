from json import JSONDecodeError
from src.helpers.file_helper import read_eval_fixture, read_questions

ENCODING_PROMPT = ""
REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""
QUESTIONS= ""

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
        "QUESTIONS": read_questions(__file__, True)
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

        # pause here for a bit to allow the fastembed model to download
        time.sleep(60)

        print("forgetful initalised")
        print(subprocess.run(["opencode", "mcp", "list"], capture_output=True, text=True).stdout)

        print("cloning github repo")
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
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

        print("removing repo from file system")
        subprocess.run(["rm", "-rf", REPO_DIR], check=True)
        print("repo removed")

    async def act(self) -> None:
        import os
        import json 
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        scaffold = json.loads(QUESTIONS)
        for q in scaffold["questions"]:
            q["answer"] = ""
        os.makedirs("/workspace", exist_ok=True)
        with open("/workspace/answers.json", "w") as f:
            json.dump(scaffold, f, indent=2)

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
            disallowed_tools=["bash", "web_search", "web_fetch"]
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import os
        import json

        if not os.path.exists("/workspace/answers.json"):
            print(f"EVAL_SCORE=0.0") 
            return 
        
        answers = {}
        try:
            with open("/workspace/answers.json", "r") as f:
                answers = json.loads(f.read())
            answers_dict = {a["id"]: a["answer"] for a in answers["questions"]}
        except(OSError, ValueError, KeyError, TypeError):
            print("EVAL_SCORE=0.0")
            return

        correct = 0 
        try: 
            scaffold = json.loads(QUESTIONS)

            for q in scaffold["questions"]:
                answer = str(answers_dict.get(q["id"], "")).strip().upper()
                if answer == q["answer"].strip().upper():
                    correct += 1 

            score = correct / len(scaffold["questions"]) 
            print(f"EVAL_SCORE={score:.4f}")
        except JSONDecodeError as e:
            print(f"Error parsing answer file: {e}")
            print("EVAL_SCORE=0.0")
        except Exception as e:
            print(f"Error scoring forgetful encode eval: {e}")
            print("EVAL_SCORE=0.0")

        
    
