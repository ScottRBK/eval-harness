# Search with Questions and Answers 

This eval measures two things:
1. The ability of an agent to encode information about a github repo in to a knowledge base.
1. The ability to retrieve information from about the github repo using only the knowledge base.

## Overview 
For this example we are using [typer](https://github.com/fastapi/typer), a popular Python library for 
helping build CLI applications. In reality, a lot of these answers might come from the model weights 
itself as it is a very popular public Python library, however the point is to just demonstrate the pattern.
When building a similar evaluation, then you will want to use a private repository.

> [!TIP]
> To point this eval at a **private** repository, set `EVAL_HARNESS_GITHUB_TOKEN` in `.env` to a
> token that can read it. The harness injects it into the container as `GH_TOKEN`, and the clone in
> `arrange()` runs `gh auth setup-git` (guarded on the token being present) so the HTTPS `git clone`
> authenticates. See [authorisation](../authorisation.md#private-repositories-harness-level-github-token)
> for details. Leaving the token unset keeps public-repo clones working anonymously.

For the knowledge base I am using the [forgetful](https://github.com/ScottRBK/forgetful) which is my
own MCP memory system for AI Agents. 

The evaluation as well also demonstrates how you can use [agent-shell](https://github.com/ScottRBK/agent-shell)
to add and list MCP servers to AI CLI clients and also how to disable certain tools. The ability to 
test agent harnesses with and without certain tools is really powerful.


## Evaluation Details

###  arrange
The arrange phase begins by starting the mcp server locally and then adding it to the agent harness
as an mcp tool. We also add a pause in here at this point because we need to wait for some of the 
activity on the MCP server to stand up - i fully admit there is probably a better way of handling this. 

```python 
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
```

After this we then wait for the mcp to initalise, given it is running locally we need to wait for
the first time initialisation of forgetful. We poll the mcp server list of the agent harness to determine
if the mcp server is ready, we give it a grace period of 2 minutes, which if we exceed we raise a 
runtime error and fail that particular agents run.

```python
timeout = 2 * 60
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
```
We then run a subprocess to clone the github repo, if we have a token then we run the auth command, 
you can in theory skip this step for public repos, I have only left it in there as a demonstration for
in case you need to evaluate a privte repo, which obvious requires auth to github.

```python
# When a private repo is targeted, GH_TOKEN is present in the container env and we
# register gh as git's credential helper so the HTTPS clone authenticates. Guarded
# so public-repo runs (no token) clone anonymously and gh is never given a blank token.
if os.environ.get("GH_TOKEN"):
    subprocess.run(["gh", "auth", "setup-git"], check=True)
subprocess.run(
    ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
     "--depth", "1", "--branch", REPO_REF, REPO_URL, REPO_DIR],
    check=True,
)
```

Once we have the repo cloned we then call agent shell passing the agent information along with our
encoding prompt, which we populated at the top of the file using a [`read_eval_fixture`](../helpers.md) 
helper from our [embedded-values](../../README.md#embedded-values). 

The [encoding prompt](../../example_evals/encode_repo_forgetful/fixtures/encoding_prompt.md) is a 
mark down file with instructions telling the agent how they should encode a repo into the forgetful 
knowledge base. 

```python
shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
response = await shell.execute(
    cwd=REPO_DIR,
    prompt=ENCODING_PROMPT,
    model=os.environ["AGENT_MODEL"],
    effort=os.environ["AGENT_EFFORT"],
)
```

Finally just to wrap up we remove the github repo - this is an important step for this particular 
evaluation as we want the agent to solely rely on knowledge held within it's own knowledge base.

```python
subprocess.run(["rm", "-rf", REPO_DIR], check=True)
```
### act

The first thing we do in act is take the `QUESTIONS` file that we have generated using the 
[`read_questions`](../helpers.md) helper in the embedded values for act and then write that to a file
in the workspace of the container called `answers.json`. When we declare the variable and populate it 
using the `read_questions` helper we set the `include_answers` boolean to false, ensuring the file
does not have any of the answers populated and in addition to this the source and notes columns are 
removed entirely as well.

```python
os.makedirs("/workspace", exist_ok=True)
with open("/workspace/answers.json", "w") as f:
    f.write(QUESTIONS)
```

After which we then call `agent_shell` asking the agent to populate the multiple choice answers in the 
JSON file. In this section as well, we make use of one of the agent-shells useful features, the ability
to disable tools that the agent harness is using for the evaluation. This is possible by passing
a list of tools we want to disable to the `disallowed_tools` parameter. 

> [!WARNING]
> There are some limitations around the `disallowed_tools` feature depending on the CLI harness you are working with, so be sure to read more about it [here](https://github.com/ScottRBK/agent-shell#restricting-tools-disallowed_tools).

### score 

Firstly we start by checking that the answers.json is actually there, if it is not we exit out of the
function and emit an `EVAL_SCORE=0`. 

```python
if not os.path.exists("/workspace/answers.json"):
    print(f"EVAL_SCORE=0.0") 
    return 
```

We then load up the agent answers file from the workspace, and compare the values against the actual answers
that are held as an embedded value in the score script named `ANSWERS`

This allows us to then compare the two and count the number of correct Answers

```python 
for q in scaffold["questions"]:
    answer = str(agent_answers_dict.get(q["id"], "")).strip().upper()
    if answer == q["answer"].strip().upper():
        correct += 1 
```

For the score we simply take the number of correct values and divided it by the total number of questions
giving us a value between 0 and 1 for the score, meaning that if we answered all questions 100% correct then
the score would be 1. 

We then emit this back as a print statement which will get collected from the docker container by the
eval harness process

```python
score = correct / len(scaffold["questions"]) 
print(f"EVAL_SCORE={score:.4f}")
```

