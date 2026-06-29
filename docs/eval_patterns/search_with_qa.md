# Search with Questions and Answers 

## Overview 
This eval measures two things:
1. The ability of an agent to encode information about a github repo in to a knowledge base.
1. The ability to retrieve information from about the github repo using only the knowledge base.

For this example we are using [typer](https://github.com/fastapi/typer), a popular Python library for 
helping build CLI applications. 
> [!NOTE]
> In reality, a lot of these answers might come from the model weights itself as it is a very popular public Python library, however the point is to just demonstrate the pattern.
> If you wanted to a similar evaluation, then you will want to use a private repository.

For the knowledge base I am using the [forgetful](https://github.com/ScottRBK/forgetful) which is my
own MCP memory system for AI Agents. 

The evaluation as well also demonstrates how you can use [agent-shell](https://github.com/ScottRBK/agent-shell)
to add and list MCP servers to AI CLI clients, which I think is a capability for measuring various harness
capabilities. 

Another thing to comment on at this stage is that perhaps you would be better off measuring these two
activities in isolation, so an eval for encoding data in there and evaluation for just answering the 
questions using a pre-seeded knowledge base, however this evaluation is measuring search and retrieval 
capabilities across two mediums (file system and a vector-graph).

## Evaluation Details

###  arrange
The arrange phase starts by starting the mcp server locally and then adding it to the agent harness
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

        # pause here for a bit to allow the fastembed model to download
        time.sleep(60)
```
We then print a list of mcp servers as confirmation before cloning a repo to the directory that we specified
in the embedded values: 

```python
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
> There are some limitations around this feature depending on the CLI harness you are working with, so be sure to read more about it [here](https://github.com/ScottRBK/agent-shell#restricting-tools-disallowed_tools).

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

