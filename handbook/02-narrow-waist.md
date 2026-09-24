# One recording path

A model reports SQL injection on a quote endpoint. There is no request in the record and no response. The finding carries a title, a severity of critical, and a paragraph of impact that reads like every other paragraph of impact you have ever read. It goes in the PDF. Someone forwards the PDF to a development team, and an engineer who actually looks writes back to say the endpoint returns the same page for every input.

Notice where that went wrong. Not when the model produced the sentence. Producing plausible sentences on demand is the whole product, and no amount of scolding changes what the thing is. It went wrong when the sentence acquired an identifier and a row, because from that moment every consumer downstream treated it as something established rather than something asserted. The report generator does not know the difference. Neither does the reviewer skimming a stack of findings before a client call.

The instinct is to write a better instruction. Tell it to report only what it can prove, demand evidence, threaten it a bit. I have written those prompts. They help, in the way a sign helps. The trouble is arithmetic: your instruction is one instruction in a window that also contains the crawl output, the tool catalogue, the methodology, and the part of the system prompt that made the model eager in the first place, and it is competing with all of them. Worse, when the instruction does work you have delegated the check to the component that made the claim. That is not a check. That is a second opinion from the same person.

So the control has to sit somewhere the model is not. Chapter 01 put the choosing outside the model. This chapter puts the recording outside it.

## Use one recording interface

The rule is one sentence and everything after it in this chapter is a consequence: each kind of side effect has exactly one writer, and none of the writers is the model.

<!-- num-ok: one method is a spelled quantity counting a code artifact: the single finding-write method this chapter is about, add_finding in core/store_protocol.py; the concrete store behind that interface is withheld -->
In practice that is two waists at different heights. Everything downstream of a tool execution, the timeline entry, the coverage row, the status update the dashboard polls, the memory record, the chain triggers, goes through a single shared write path, `[[code:result_processor.py:process_tool_result]]`, that takes the tool call and the tool result as its arguments and runs once per execution. Underneath it, findings have a waist of their own: one method on the store, with a single production definition, which every skill and every orchestrator calls. There is no second way to write a finding.

That gives the model exactly one verb. It proposes. A proposal is a tool name and an argument dictionary, and what happens next is not up to it: deterministic code validates the proposal, executes it if it survives, and records what came back. The model's sentence about what it expects to happen is not recorded anywhere that a report can read. What gets recorded is what the executor observed.

Follow a hallucination through that and the failure mode changes shape.

<!-- num-ok: 404 is the HTTP status code for Not Found, the protocol constant naming what a server returns for a path that does not exist; it identifies a response, it does not count one -->
The model invents an endpoint. It is a good invention, the kind of path a competent tester would also have guessed at. The executor requests it and gets a 404. The 404 is a fact about the target, it goes in the coverage table with the URL and the timestamp, and the next scoring pass can see that this path was tried and found absent. The invention cost one request and produced a true row. What it did not produce is a finding: the executor records what it observed, and the model's expectation is not one of its inputs.

Now the case that does not resolve so tidily, and I have to be careful here, because the tidy version is the one I would rather tell. Suppose the model skips the endpoint and asserts the finding directly. On the server-driven path it has no move: the executor accepts tool calls and nothing else, and findings are produced by tools returning them. On the agent-driven path there is a door. The command-line interface every skill writes through has a subcommand that stores a finding from a JSON blob, and an orchestrator that wants to record something it believes can use it.

What the door does not let you skip is the store method on the other side. That method validates the finding and then hands it to a deterministic governor which grades how replayable the evidence is: a captured request and a captured response is strong, one of the two is moderate, and a bare assertion with neither is thin. Thin evidence is capped at medium by a rule in code, before the row exists. So the finding from the first page of this chapter, critical injection with no request and no response, does not get stored as a critical. It can be stored. It arrives as a medium, in a table, carrying a governance record naming what capped it.

The same caveat I am about to give the critic applies here as well, and naming one hatch while quietly keeping the other would have this chapter contradicting itself within the same page. The governor sits behind two environment switches, one for governance as a whole and one for the evidence ceiling specifically. Both default to on. The call is also wrapped so that any exception inside it is logged at debug level and the write carries on ungoverned, on the reasoning that governance must never be the thing that stops a finding being recorded. I agree with the reasoning. I still think a control that fails open should announce it louder than a debug line.

That is a weaker guarantee than "it cannot happen" and it is the one that is actually true. The waist does not stop a model writing a sentence. It stops the sentence reaching the report wearing a severity it did not earn, and it makes the model's confident nonsense land somewhere with a return code. Hallucination stops being a quality problem and becomes a wasted request and a downgraded row.

The second thing the waist buys is a denominator. `[[stats:corpus.tool_executions]]` tool executions and `[[stats:corpus.findings.stored]]` stored findings are countable numbers because each kind of row has one writer, which is also what makes it meaningful to say `[[stats:corpus.findings.false_positive]]` of those findings were later marked false-positive. A system with three write paths has three populations and no denominator, and every honesty section in this handbook depends on there being one.

The third thing I did not appreciate until I had lived with it. The waist is where the checks go. Severity governance is not a stage somebody remembers to run; it is a line inside the method that writes findings, so a finding cannot exist without having passed it. Chapter 03 takes that mechanism apart. The structural point here is only that it had somewhere to stand, and that every control in this handbook is enforceable for the same reason.

Two honest limits before I go further.

The first: of the two waists, the shared write path now ships as `[[code:result_processor.py:process_tool_result]]` and the finding-write method as the store interface `[[code:store_protocol.py:add_finding]]`, while the concrete store behind that interface stays in the working system. The grounding critic below ships as `[[code:critic.py:score_grounded]]`. So more of this section is runnable than when it was first drafted, when all of it was prose; what is still only described, and not shipped, is the concrete store, the two orchestrators that drive the waist, and the server-side model grader the last section reaches. Chapter 01 made the same admission about the stage machine, and the honest version now is that the controls this chapter turns on stand in `core/`, while the plumbing that wires them into a live scan does not.

The second is worse, and the door above was its small version. There are two orchestrators. When a server-side model drives the run, the waist holds in the one way a record needs it to: the model emits JSON, the only thing that reads that JSON is the executor, and everything it asks for arrives as an execution the executor runs and logs. A shell command is one of the tools on that list, so what it can do is unbounded; what is bounded is that none of it happens off the record. When a coding agent drives the run, which is the default path, the waist is a convention the agent follows. It has a terminal of its own, outside that list entirely. Nothing physically stops it curling the target directly and writing prose about what it saw, and nothing in the scan record would show that it had. Everything in the skill definition tells it not to, and in practice it does not, and "in practice it does not" is precisely the sentence chapter 01 refused to accept about stage ordering. Gating the agent's tool namespace so the shell is not reachable during a scan is the fix, and it is not built on either path: the server-side orchestrator does gate its tool list per phase, which is chapter 01's Layer 0 fix already standing, and it puts a shell command in that list anyway. Until one of them closes it, the strongest control in this chapter is enforced by good behaviour on the path most people will use.

## What the validator actually does

`[[code:llm_control.py:ToolCallValidator]]` stands between a model's raw text and the executor, and it is built out of four stages that run in order. Parse the JSON, stripping markdown fences first, because models fence things. Check that `name` is a string and `arguments` is an object. Check that `name` is in the registry the validator was constructed with. Then check every argument against the schema for that tool.

The third stage is the one that turns a whole class of hallucination into a caught error. `[[code:llm_control.py:_check_tool_in_registry]]` compares the name against a dictionary and raises when it misses, and the message it raises with names the tool and lists every tool that does exist:

```
[stage:tool_registry] unknown tool 'exploit_everything'. Known tools: ['fetch_url']
```

Models invent tool names constantly. They invent them in the shape of the tools you gave them, which is why the invention is convincing and why a fuzzy check would be a mistake. Dictionary membership has no opinion about how plausible `test_auth_bypass` sounds next to `test_auth`.

The fourth stage is where two impulses pull against each other in the same loop. `[[code:llm_control.py:_validate_args]]` walks the model's arguments and throws away every key the schema does not name; for the keys it does name, it calls out to a type check that would rather bend a value into shape than reject it. Strictness and tolerance, back to back.

Dropping is the security half. The comment in the source calls it strict control against payload injection, and the mechanism is a `continue` inside the loop over the model's arguments: a key that is not in `properties` never reaches the normalised dictionary the executor receives. Hand it a call with a stowaway and the stowaway is gone.

```
in:  {"url": "https://h/", "payload": "'; DROP TABLE--", "timeout": 5}
out: ToolCall(name='fetch_url', arguments={'url': 'https://h/', 'timeout': 5})
```

Coercing is the tolerance half, and it exists because models are sloppy about types in specific, predictable ways. `[[code:llm_control.py:_validate_type]]` turns a quoted integer into an integer, a bare number in a string field into a string, and the strings `true` and `false` into booleans. It refuses to treat a boolean as either an integer or a string, which is the one coercion that would be silently destructive. The tolerance is deliberate and I think it is correct. A run that dies because the model wrote `"30"` where the schema wanted an unquoted integer has spent a repair cycle on nothing.

## Known validation gaps

I went looking for the seam between those two halves, because dropping and coercing are both silent and silence compounds.

Here it is. The drop applies to every unrecognised key, including one that is a typo of a real optional parameter. Nothing reports it. The schema's default then fills the gap, and the call validates:

```
in:  {"url": "https://h/", "timeoutt": 30}
out: ToolCall(name='fetch_url', arguments={'url': 'https://h/', 'timeout': 10})
```

The model asked for a longer timeout. It got the default. It was not told, the executor cannot tell, and the repair loop never runs because from the validator's point of view nothing failed. If the misspelled key had been required the error would have fired, so the failure is confined to optional parameters, which is exactly where a silent wrong value is hardest to notice later.

That one is caused by the drop being a `continue` rather than an error, and I checked rather than assumed: subclass the validator so an unknown key returns a failure instead of skipping, feed it the same call, and the repair loop fires and re-prompts. Same input, different behaviour, so the mechanism I am blaming is the mechanism responsible.

<!-- num-ok: two functions is a spelled quantity counting a code artifact: _validate_args and _validate_type, the two ToolCallValidator methods in core/llm_control.py where the dropping and the coercing this section opens on happen, and where all three defects below sit -->
Three smaller ones, all in those same two functions.

A required parameter that also carries a default is not required. Defaults are applied before the missing-argument check runs, so the check never sees a gap. A schema author who writes both is telling the validator two things and only one of them survives.

An unrecognised `type` keyword disables checking for that property. The final branch accepts anything for forward compatibility, which is a defensible choice, and it means a schema with `"strng"` in it validates a nested object as a string and nobody hears about it.

And the number branch accepts any string Python's `float()` accepts, which includes `nan` and `Infinity`. A rate limit of not-a-number passes validation cleanly.

None of these will ruin your day. I list them because they are the same species as chapter 01's dead penalty entries: nothing breaks, nothing logs, the tool behaves correctly throughout, and the only way to find them is to sit down and enumerate the cases. Which nobody does, me included, until there is a chapter with a deadline attached.

## The repair loop

When validation fails, `[[code:llm_control.py:repair_loop]]` builds a prompt out of the failure and asks again. The prompt carries the original response verbatim, the exact error with its stage tag, the list of known tools, and, when the error message named a tool the registry recognises, that tool's full schema. Then it re-runs the entire pipeline on whatever comes back.

The budget is the `[[code:llm_control.py:max_retries]]` parameter, which defaults to three. Read that as three re-prompts and four validation attempts, since the first attempt happens before any repair. Set it to zero and you get validation with no second chance and no model call. If the last attempt still fails, the final `[[code:llm_control.py:ValidationError]]` is raised rather than swallowed, which matters: a call that cannot be repaired is an error the orchestrator has to handle, not a silently dropped turn.

What makes the loop work is that the error messages were written for a reader. `[[code:llm_control.py:_build_repair_prompt]]` extracts the tool name out of the error text with a regex and attaches the schema, so the model is not asked to guess what shape was expected. That is a small piece of engineering with a large effect, and it is the sort of thing that gets skipped when the error strings are written for a log file instead of for the thing that has to act on them.

I have no measurement of how often repair succeeds. The corpus does not carry per-call validation outcomes, so any number I gave you would be invented, and there is a real question underneath the missing number: a model that emitted invalid JSON once may be in a state where it will do it again, and spending three more calls to find that out is not obviously the right trade. It has never cost me enough to go and find out, which is not the same as it not mattering.

## The grounding gate

Everything above is about form. A validated tool call is well-formed and its arguments have the right types, and it can still be a request to a path that has never existed, justified by a sentence about a JavaScript bundle the model did not read.

So there is a second gate, and it is the piece of this design I would defend hardest. It also exists in two implementations, and they are not the same check.

Both start the same way. Every proposal the model emits carries an evidence pointer: a source label, a short quoted snippet, and a reference naming where in the context the snippet came from. What happens to that pointer depends on which orchestrator is running.

On the server-driven path the grader is a second model, called once per batch rather than once per item. It gets the context, the batch, and a rubric, and the rubric is deliberately forgiving: the reference counts if it or a clearly equivalent phrase appears, and the snippet counts if it is near-verbatim rather than exact. Each item comes back with a confidence and the low ones are dropped.

On the agent-driven path there is no second call. The check is string containment, run in Python. Does the reference appear in the context, and does the opening stretch of the snippet appear in it. Not "is it consistent with", not "does a reviewer find it reasonable". Does the substring occur.

I want the containment one, and the reason is the property only it has: there is nothing in a substring search to argue with. A rubric handed to a model can be argued with, and arguing with rubrics is close to the thing models are best at. The registry check a few pages back has the same virtue for the same reason, and it is worth noticing that the checks in this system nobody can argue with are the dumb ones. What I should not have done, and did, is attach that property to the gate as a whole. The tell was in my own escape-hatch section below: a provider outage is not a failure mode a string search has.

Now the part that took me two attempts to get right.

### Separate proposal and finding gates

Run that check over everything a model proposes and you will destroy your scan. I know because that is what the first version did.

Sort the model's output into two piles.

The first pile is claims about observed reality. "This bundle references an admin path." "This response header is missing." "This parameter appears in three forms." Every one of these is a statement about a document that was in the context. If the model read it, the string is there. If the model generated it from its prior about what such things look like, the string is not there. Containment decides the question, right now, for free.

The second pile is proposals about the future. "Send a POST to that path with a modified identifier and see whether it returns another tenant's record." This is not a statement about anything. It is an instruction. The response it is about does not exist yet, and will not exist until the instruction is carried out.

Here is the sharp version. A proposal is not fully uncheckable. It has a premise, the endpoint it names, and the premise is quotable. What is not quotable is the proposal's actual content: whether the test is worth running, whether the identifier is manipulable, whether another tenant's record comes back. Containment can verify the noun and has nothing to say about the verb. For an observation, the noun is the whole claim. For a proposal, the noun is only the footing.

Which gives the rule I would put on a wall. Gate a statement against the thing that could falsify it. An observation is falsified by the artifact, and the artifact is sitting right there, so an observation that will not quote it gets dropped. A proposal is falsified by execution, and execution has not happened, so a proposal gets scored and kept and allowed to fail in reality.

<!-- GROUNDED_PHASES in core/critic.py is the frozen set of grounded stage names, and its membership is the whole of the surface-or-proposal split -->
The categories are not the model's to assign, which matters more than it sounds. The category comes from the pipeline stage that produced the batch, and the stages are a fixed set of names in the orchestrator's code. There is a frozen set, `[[code:critic.py:GROUNDED_PHASES]]`, holding the stage names that get the hard gate; membership in it is a property of the stage, not a property of the proposal. A model cannot argue its way from one pile to the other by writing a more confident sentence, because it is never asked which pile it is in.

### What breaks if you collapse it

Collapse the two into one by gating nothing, and you have the report from the first page of this chapter. Note which pile leaks. Ungated proposals are self-correcting: a bad one becomes a request and the request comes back with a status code, and the cost is a few seconds. Ungated observations become findings. The pile you can afford to leave open is not the pile that reaches the PDF, so "gate nothing" fails asymmetrically, in the direction that hurts.

Collapse them the other way and gate everything, and the system goes quiet. Forward-looking proposals score at the floor, every time, because they are being asked to quote a request that has not been made. They are not scoring badly. The check has been handed a question with no true answer, and it answers anyway.

This is not hypothetical. The first version of this gate applied the quote test to every stage, and on a live run against a real target the chain-analysis stage lost its entire batch: every item graded as invented, because none of them could cite a response that did not exist yet. What frightens me is the symptom. Nothing errors: no exception, no failed assertion, one warning in a log nobody was reading. The scan runs the catalogue, proposes nothing beyond it, finishes, and produces a report that says the target is clean. A blinded scanner and a hardened target are indistinguishable from the outside, and the blinded scanner is the one that flatters everybody.

I made this mistake myself, in the direction that goes blind, and it took a while to notice. What makes it easy to make is that both collapses read as reasonable in a design document: one says trust the model, the other says verify everything, and neither of them stops to ask what the verification is actually able to decide.

### Remaining bypasses

<!-- num-ok: Three places is a spelled quantity counting a code artifact: the three this section then describes one at a time, and the same sentence splits them two found while writing plus one found by a reviewer -->
Three places, all real, all in the working system rather than in the argument. I found two of them while writing. A reviewer found the third, and the third is the one that matters.

Start there, because it is the one a reviewer found and the one this section was first written to confess. In the system this chapter re-expresses, the containment implementation read a `confidence` field off the incoming item and, when the caller supplied a number, used it in place of the containment score it had just computed. The reference check and the snippet check ran first; the caller's number then won the branch after them. The server-driven path never reached that code, since it grades with the second model instead, so the channel lived on the agent-driven path only, where the caller is the orchestrator and the orchestrator is a model.

The hole ran both ways, which is what made it the one that mattered. An invented endpoint whose reference and snippet appeared nowhere could be handed a caller-supplied confidence above the threshold and clear the hard gate untagged; and a genuinely grounded item scored at zero by the caller was the one that got dropped. A channel that can smuggle an invented finding in can also make a real one vanish, and for a security tool the second direction is the worse of the two: somebody eventually argues with a finding that is wrong, and nobody argues with the finding that is not in the report. Worse, the containment answer that would have contradicted the caller was written with a `setdefault`, so a caller supplying its own notes overwrote the record as well as ignoring it.

The re-expression in `[[code:critic.py:score_grounded]]` does not carry that hole, and the difference is the asymmetry chapter 03 applies to severity. The reported confidence is the `min` of the containment score and any caller-supplied one, so a caller's number can only lower it, never replace or raise it. The keep-or-drop test reads the containment score rather than the reported one, so an invented item self-scored high is still judged at its containment and still dropped, and a grounded item self-scored zero is reported low and kept. And the gate's own containment record is written under its own key on every pass, from its own measurement, with a caller's notes moved aside rather than allowed to overwrite it. So on this path a caller can no longer grade its own claims past the gate, which is what the first draft of this section, written before the fix shipped, said it could.

A caller channel does remain, and naming it is the honest part of the fix. When every item in a batch is dropped, the floor keeps the strongest of them, and it orders that pile by the reported confidence a caller can pull down. So a caller can still choose which single item survives a batch that was going to be emptied, though it can neither flip a verdict nor enlarge the kept set. That residual is the escape hatch below, not a second grading channel, and it is one reason the section that follows exists.

The second. The stage label is a literal at the call site when a server-side model orchestrates. When a coding agent orchestrates, the stage label is a field the agent passes in. The default is the strict stage, so an agent that omits the field gets the hard gate, which is the correct direction to fail. An agent that declares the wrong stage turns the gate off for that batch. Nothing validates the declaration, because the thing that would have to validate it is the thing making the declaration. I do not have a clean answer to this one. The honest description is that the gate is structural on one path and self-reported on the other.

The third, also found while writing this chapter, which is becoming a pattern I should probably read something into. The observed-reality batch is assembled from two model calls: one over crawl and form data, one over the JavaScript source. The grounding check runs against the context of the first call only, because that is the last context the object recorded. So an endpoint the model genuinely read out of a bundle, correctly, verbatim, gets checked against a context that never contained the bundle, and is dropped for failing to quote a document it was never compared with. False drops are the quiet cost of a gate set too tight, and here is one built into the wiring rather than into the threshold.

## The escape hatch, and what it costs

The gate is not absolute, and a reader who takes away that it is has taken away something false.

Two things can go wrong, and they belong to different implementations.

The model-graded path can lose its grader: a timeout, a provider outage, a response nothing can parse. When that happens the batch passes through untouched, every item stamped with a neutral confidence and a note carrying the error, and nothing is dropped. For that batch the gate is off and the record says so. The containment path has no such mode, because there is no call in it to fail.

The second failure belongs to both. If the grader runs fine and rejects everything, the batch is not emptied. The rejected items are sorted by confidence, the highest one is kept, and it is tagged as a forced keep. The comment in the source says it plainly: never stall.

The cost of that second case deserves stating without decoration. The surviving item is, by construction, an item the gate judged ungrounded. It is the best of a bad batch, and the batch was all bad. The gate's floor is one, not zero. A stage whose every proposal was invented yields one invented proposal that goes forward, wearing a tag.

I keep the hatch, and I will defend the reasoning while admitting it is a trade rather than a fix. A scan that stalls produces nothing at all, and nothing is not a safer output than one weak proposal, it is a different failure that happens to be quieter. The blast radius is also smaller than it first looks, and that is the narrow waist paying for itself: the items this gate governs are proposals for tools to run, not findings. A forced-keep item becomes a tool execution against a possibly-invented URL, and before it gets there it meets the injection filter: unknown tool names go, so do parameter-hungry tools aimed at parameterless URLs and the small vocabulary of placeholder hostnames models reach for when they are guessing, and there is a cap on how many injections a run will take at all. Then the target gets the last word.

<!-- score_grounded in core/critic.py writes the critic_forced_keep tag on a forced keep, and production code only ever writes it -->
<!-- num-ok: Three tests is a spelled quantity counting a code artifact: the tests that assert on this tag, in tests/test_critic.py -->
What I do not like is the tag. `critic_forced_keep` is written onto the item and, as far as I can find, nothing downstream ever reads it. Three tests assert on it and no production code branches on it. So the information exists and is not used, and the obvious improvement is to make the hatch a quarantine rather than a promotion: let the item through, but mark the results it produces as provisional and keep them out of any severity above the floor until something else corroborates them. That is maybe an afternoon of work and I have not done it, which is a more accurate statement about my priorities than about the design.

## What the gate does not do

It stops one specific failure: an assertion about observed data that cannot quote the data. That is worth having and it is narrower than the phrase "anti-hallucination" invites you to believe.

A finding can be perfectly grounded and completely wrong. The quote is real, the endpoint exists, the response was captured, and the inference drawn from all of it is nonsense. Containment has nothing to say about inference, and neither does anything else in this chapter.

The number, which I would rather you got from me than discovered later. In the selected public-target aggregate, `[[stats:benchmark.juice_shop.n]]` author-recorded run, the recorded precision was `[[stats:benchmark.juice_shop.included.0.precision]]`: `[[stats:benchmark.juice_shop.included.0.false_positives]]` of `[[stats:benchmark.juice_shop.included.0.findings_count]]` findings were labelled false positives after every control described in this chapter had run. Chapter 05 reports that aggregate with its exclusions and its evidence limit: this repository does not contain the raw findings, ground truth or matcher needed to reproduce those labels. It is not a benchmark result. It is enough to kill the reading where a validated tool call plus a quoted snippet automatically adds up to a trustworthy finding. All that buys you is a finding which is about something real, and being about something real is the floor.

The rest of the distance is severity governance and verification, which is chapter 03, and honest reporting of what was not covered, which is chapter 05. Both of those are checks, and the waist is the reason there is anywhere to put them.

## What it costs to build this

<!-- num-ok: one function is a spelled quantity counting a code artifact: the single shared write path this whole chapter is about, process_tool_result in core/result_processor.py -->
The discipline is the cost, and it is paid continuously. Every new side effect has to be routed through the one function, and every new side effect arrives with a reason it should be an exception. This one is just a log line. This one only writes to a cache. Each exception is individually reasonable and the second write path is where the property dies, because the moment there are two, "everything went through here" stops being true and every count built on it becomes an estimate.

<!-- num-ok: one function is a spelled quantity counting a code artifact, used twice on this line for the same single shared write path named in the paragraph above -->
The one function is also one function that can be wrong about everything. It writes in a deliberate order because later steps read state earlier steps wrote, and each step catches its own exception and appends to an error list rather than raising, so one failed side effect does not take the rest down. That is the right call under load and it means a partially-written result is a normal outcome that callers have to actually inspect. A caller that ignores the error list gets silence where it wanted a guarantee.

The evidence pointer is a tax on the model's output. Every proposal has to carry a quote, which costs tokens and occasionally costs a good idea from a model that could not find a snippet to justify an instinct. I think the trade is obviously right, and I notice that "obviously" is doing work I have not measured.

And the gate needs a threshold, which means it needs tuning, which means somebody has to decide how much false-dropping is acceptable. There is no principled answer. There is a number in a file, an environment variable to change it, and the observation that both directions have a cost, one loud and one silent, and the silent one is the one that eats scans.
