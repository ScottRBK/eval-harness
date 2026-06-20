from src.helpers.file_helper import read_eval_fixture, read_mapping

REPO_SALEOR_URL = ""
REPO_SALEOR_REF = ""
REPO_SALEOR_DIR = ""
REPO_SPREE_URL = ""
REPO_SPREE_REF = ""
REPO_SPREE_DIR = ""
MASKED_MAPPING_DOC = ""
MAPPING_PROMPT = ""
CANONICAL_MAPPING_DOC = ""
MAPPING_OUTPUT_PATH = ""

class SaleorSpreeMapping:
    
    arrange_embedded_values = {
        "REPO_SALEOR_URL": "https://github.com/ScottRBK/saleor",
        "REPO_SALEOR_REF": "eval-v1",
        "REPO_SALEOR_DIR": "/workspace/saleor",
        "REPO_SPREE_URL": "https://github.com/ScottRBK/spree",
        "REPO_SPREE_REF": "eval-v1",
        "REPO_SPREE_DIR": "/workspace/spree",
        "MASKED_MAPPING_DOC": read_mapping(__file__, "canonical_mapping.csv", ["spree_field", "transform"])
    }

    act_embedded_values = {
        "MAPPING_PROMPT": read_eval_fixture(__file__, "mapping_prompt.md")
    }

    score_embedded_values = {
        "CANONICAL_MAPPING_DOC": read_mapping(__file__, "canonical_mapping.csv"),
        "MAPPING_OUTPUT_PATH": "/workspace/mapping.csv",
    }

    async def arrange(self):
        import subprocess 

        print("cloning saleor repo") 
        subprocess.run(
                ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
                 "--depth", "1", "--branch", REPO_SALEOR_REF, REPO_SALEOR_URL, REPO_SALEOR_DIR],
                check=True,
              )
        print("saleor repo cloned")
       
        print("removing saleor git remote link")
        subprocess.run(["git", "-C", REPO_SALEOR_DIR, "remote", "remove", "origin"])
        print("saleor git remote link removed")

        print("cloning spree repo")
        subprocess.run(
                ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
                 "--depth", "1", "--branch", REPO_SPREE_REF, REPO_SPREE_URL, REPO_SPREE_DIR],
                check=True,
              )
        print("spree repo cloned")

        print("removing spree git remote link")
        subprocess.run(["git", "-C", REPO_SPREE_DIR, "remote", "remove", "origin"])
        print("spree git remote link removed")

        with open("/workspace/mapping.csv", "w") as f:
            f.write(MASKED_MAPPING_DOC)

    async def act(self):
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType
        
         
        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
        print("calling agent")
        response= await shell.execute(
            cwd="/workspace/",
            prompt=MAPPING_PROMPT,
            model=os.environ["AGENT_MODEL"],
        )

        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self):
        import csv
        import io
        import os

        try:
            canonical = {}
            for row in csv.DictReader(io.StringIO(CANONICAL_MAPPING_DOC)):
                canonical[row["saleor_field"].strip()] = (
                    row["spree_field"].strip(),
                    row["transform"].strip().lower(),
                )

            if not os.path.exists(MAPPING_OUTPUT_PATH):
                print("agent produced no mapping file")
                print("EVAL_SCORE=0.0")
                return

            answers = {}
            with open(MAPPING_OUTPUT_PATH, newline="") as f:
                for row in csv.DictReader(f):
                    answers[row.get("saleor_field", "").strip()] = (
                        row.get("spree_field", "").strip(),
                        row.get("transform", "").strip().lower(),
                    )

            total = len(canonical)
            correct = sum(
                1 for field, expected in canonical.items()
                if answers.get(field) == expected
            )

            score = correct / total if total else 0.0
            print(f"matched {correct}/{total}")
            print(f"EVAL_SCORE={score:.4f}")

        except Exception as e:
            print(f"Error scoring saleor spree mapping eval: {e}")
            print("EVAL_SCORE=0.0")
