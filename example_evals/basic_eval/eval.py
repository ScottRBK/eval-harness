from src.helpers.file_helper import read_questions, read_eval_fixture
QUESTIONS = "" 
PROMPT = "" 
ANSWERS = ""

class BasicEval:

    arrange_embedded_values = {
        "QUESTIONS": read_questions(eval_file=__file__, include_answers=False)
    }

    act_embedded_values = {
        "PROMPT": read_eval_fixture(eval_file=__file__, relative_path="prompt.md")
    }
    
    score_embedded_values = {
        "ANSWERS": read_questions(eval_file=__file__, include_answers=True) 
    }

    async def arrange(self):
        import os 
        import subprocess 
        # 1 . clone a repository 

        print("cloning eval harness repo")
        subprocess.run(
            ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch",
             "eval-1", "https://github.com/ScottRBK/eval-harness", "/workspace/eval-harness"],
            check=True
        )
        print("cloning completed")

        # 2 . generate a questions for the agent to read 
        os.makedirs("/workspace", exist_ok=True)
        with open("/workspace/answers.json", "w") as f: 
            f.write(QUESTIONS)


    async def act(self):
        import os 
        from agent_shell.shell import AgentShell 
        from agent_shell.models.agent import AgentType 

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))

        print("call agent for basic eval") 
        response  = await shell.execute(
            cwd="/workspace",
            prompt=PROMPT,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
        )
        print(response.response)
        print(f"Session: {response.session_id}")

    async def score(self): 
        import os 
        import json 
        # 1. make sure that we can load the agents answers correctly and they parse 
        if not os.path.exists("/workspace/answers.json"):
            print("unable to detect answers file")
            print("EVAL_SCORE=0.0")

        agent_answers = {} 
        try:
            with open("/workspace/answers.json", "r") as f: 
                agent_answers = json.loads(f.read()) 
            agent_answers_dict = {a["id"]: a["answer"] for a in agent_answers["questions"]}
        except(OSError, ValueError, KeyError, TypeError) as e: 
            print(f"Unable to open agent answers.json: {e}")
            print("EVAL_SCORE=0.0")
            return 
        
        # 2. compare the agents answers with the actual answers in the fixtures directory
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
            raise RuntimeError("Invalid answers.json fixture file") from e
        except Exception as e: 
            raise RuntimeError("Error scoring basic eval agnet") from e

                
