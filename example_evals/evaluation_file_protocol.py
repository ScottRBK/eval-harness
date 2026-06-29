"""
Protocol for building an evauluation file:

Evaluation Files act as a means of supplying python scripts required to perform three stages
of the evaluation, following arrange-act-assert principle from automated software testing:
- Arrange 
- Act 
- Assert (renamed to Score as Assert is a python keyword in the std lib)

The contract for the Evaluation File Protocol stipulates that there must be three methods:
*Arrange* - data and infrastrcuture setup for the the specific evaluation, for example cloning a repo,
installing any specific service or software inside the isolated docker container
*Act* - This aspect of the script sees the agent go ahead and perform the task that the output of which
shall be evaluated in the Score phase
*Score* - phase responsible for evaluating the output of the task

Important considerations for each evaluation file:
- Any import statements must be lazy loaded inside the methods themselves    
- each stage can have key/value pairs passed to it using:
    - arrange_embedded_values, act_embedded_values, score_embedded_values

    Example: 

    act_embedded_values = {
        "ENCODING_PROMPT": read_eval_fixture(__file__, "encoding_prompt.md")
    }


"""
from typing import Protocol

class EvaluationFile(Protocol):
    async def arrange(self) -> None: ...
    async def act(self) -> None: ...
    async def score(self) -> None: ...


