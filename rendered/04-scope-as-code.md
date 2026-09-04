# Scope as code

A single-page application ships a map of somebody's estate. Open the bundle and there it is: the API host, the identity provider, the analytics vendor, the geolocation service somebody wired in during a hackathon and nobody took out. Reading that file is the job. The crawler reads it, the miner turns what it finds into candidate endpoints, the candidates become requests, and nowhere in that chain does anything ask whose host it is.

That is how an agent ends up testing infrastructure nobody authorised it to touch. No jailbreak and no adversarial prompt. Nobody decides to attack the payment vendor: its hostname arrives as a value in a config object, and values do not carry authorisation.

Then the findings go into a report with a client's name on the cover, and a section of that report is about a company the client does not own.

## What a sentence cannot do

The obvious control is an instruction. Put the scope at the top of the system prompt, list the domains, say it firmly.

Chapter 02's arithmetic applies here unchanged: your instruction is one instruction in a window that also holds the crawl output, the tool catalogue and the methodology, and it competes with all of them. Scope adds two problems that severity did not have.

The first is that a sentence cannot refuse. There is no return value to check and nothing for a caller to branch on. The model can decline, and a model declining is a behaviour rather than a mechanism. Behaviour holds until the run gets long, the context gets crowded, and a URL shows up looking exactly like the ones that were fine.

The second is that a sentence leaves nothing behind. When the run finishes, "we did not test the vendor's API" and "the vendor's API never came up" render identically, which is to say they render as nothing at all. A control that produces no record cannot be audited afterwards. I would rather have a mediocre control I can count than a good one I have to remember.

## A function returns a fact

So the scope decision is a function. It takes a URL and returns a boolean, and everything else in this chapter is a consequence of that shape.

<!-- ScopeGuard in core/scope_guard.py is the function this section describes; is_in_scope takes a URL and returns the boolean, asking the three questions in this order -->
The one I run, [`scope_guard.py:ScopeGuard`](../core/scope_guard.py), is small enough to read in a sitting: constructed with the scan's target and two optional pattern lists, out-of-scope and in-scope. The first thing it does is reduce the target to a registrable domain, which becomes the base it admits against. Then every call asks three questions in a fixed order. Does any out-of-scope pattern match this host? If so the answer is no. Does any in-scope pattern match? If so the answer is yes. Otherwise, is this host's registrable domain the same as the base? That last question is the default admission, and it is what makes a bare target usable without anyone writing a pattern list at all.

<!-- _matches in core/scope_guard.py is the pattern test this sentence describes: host-equals, subdomain-of, or shell glob -->
A pattern matches a host, by [`scope_guard.py:_matches`](../core/scope_guard.py), when it is that host, when the host is a subdomain of it, or when it matches as a shell-style glob. Point the guard at a target and it admits the target, its siblings under the same registrable domain, and hosts on any explicit in-scope pattern, on whatever port and under whatever path.

The ordering is the part that composes. Deny is asked before allow, so a hard-skip pattern carves a hole in an admission rather than arguing with it. Seed the guard with an in-scope engagement and hard-skip one subdomain of it, and that subdomain is out while its siblings stay in. Name the same pattern in both lists and the answer is no. That is the correct precedence for a control whose failure mode is testing something you should not have, and it is worth choosing deliberately rather than inheriting from whichever list you happened to loop over first.

Where the function runs matters as much as what it returns. It sits at the tool boundary: the executor pulls the declared target off the tool's arguments, asks the question, and when the answer is no the tool does not run. What comes back to the caller is a result object marked skipped, carrying the reason.

That return value is carrying more than it looks like it is. A refusal that is a value can be counted, printed, handed to a ledger and argued with. A refusal that is a model politely declining in prose is none of those things, and by the time anyone wants to know what happened it has scrolled out of the transcript.

Chapters 01, 02 and 03 each made this admission about their own subject; here the guard has since landed. [`scope_guard.py:ScopeGuard`](../core/scope_guard.py) ships in `core/`, so what follows is behaviour I ran against fictional hosts out of a scratch copy of it. It is the one part of this chapter that is code you can run: the crawler's separate check below, and the bundle miner two sections on, stay in the working system.

## Where the fact stops being a fact

Three ways the answer is wrong, and I found all three by writing the sentence I wanted to publish and then trying to break it.

<!-- _registrable in core/scope_guard.py is the base derivation this paragraph describes: the last two dot-separated labels of the host -->
Admission is computed at the registrable domain by [`scope_guard.py:_registrable`](../core/scope_guard.py), which is the last two labels of the hostname, and never at the host you were actually pointed at. Hand the guard `app.shop.example` and it admits `shop.example` and every other host under it. That is the structural fact, it holds for every target that is a subdomain, and the next section measures what it costs. The dramatic version is a target under a two-label public suffix: the same rule derives `co.uk` as the base, and an unrelated company's site under that suffix answers in-scope. A public-suffix list fixes the dramatic version and does nothing for the structural one. Neither fix is in the code.

What bothers me about the suffix case is how quiet it is. Nothing errors. The guard answers in the same voice it uses when it is right, the run proceeds, and the only way to find out is to have gone and asked.

<!-- the environment kill-switch is AUTOMATOR_SCOPE_TRACKING in core/scope_guard.py; the unseeded guard, the one whose base came out empty, is the other fail-open -->
Then it fails open twice. There is an environment kill-switch, [`scope_guard.py:AUTOMATOR_SCOPE_TRACKING`](../core/scope_guard.py), that turns the whole guard off, and a guard with no base admits everything. The second one is worth saying precisely, because the obvious reading of it is too narrow. The test is on the base the target reduced to, not on whether a target was supplied, and the base comes out empty both for an absent target and for a target that reduces to no host, so validating the constructor against a missing argument does not prevent this path. Nor does writing the host down as out of scope: the fail-open is read before either list is consulted, so a declared exclusion is admitted too. I will defend the kill-switch on chapter 03's terms, which are narrower than mine were: a control with a documented off switch is a control, not a guarantee. The unseeded case I will not defend, and chapter 02 has the distinction that condemns it. When its grounding critic loses the model that grades for it, the batch goes through ungraded and every item is stamped with the error, so the record says the gate was off for that batch. When its governor throws, the write carries on ungoverned and the only trace is a debug line, which chapter 02 said should be louder. An unseeded guard is the second kind and quieter still. It returns yes, in the same shape as a real admission, and nothing downstream can tell the two apart.

The third is the smallest, and I have to be careful about what I promise for it. Hand the guard a string with nothing host-like in it, a bare path or an empty value, and it returns true, on the argument that there is nothing here to judge. As a local decision that is defensible. It is also not the thing that went wrong at the end of this chapter, because the guard was never asked there. What recurs is the shape and not the code path: a string with no host in it gets waved through by whichever component is holding it, and the component holding it later on is not the one with the scope function inside.

## The literal host

The default admission is broader than the rule I actually work to.

The rule is: test the host you were handed. When the application calls a backend on another host, that backend gets written down and flagged for the operator, and nothing touches it. The reasons are contractual before they are technical. A different host is frequently a different team, sometimes a different vendor with its own agreement, and often a shared gateway fronting a long list of applications, one of which is yours this week. Sharing a registrable domain is a fact about DNS registration. It is not a fact about who signed what.

So the discipline is narrower than the function. And the function is not the only one: the working system carries more than one scope check, and they do not agree with each other.

The crawler carries its own check, written earlier and for a different job. It refuses anything that is not http or https. It refuses a short built-in list of hostnames outright, before any admission runs: analytics, a tag manager, a social widget, CDN telemetry, a captcha endpoint. It admits any host matching a multi-domain list when the scan supplies one. Failing all that, it admits the target host and its subdomains. So it is deny-first as well, and it carries both kinds of list, which makes the comparison more awkward rather than less. What it lacks is the registrable-domain widening, and its deny list is exact hostname membership rather than a pattern. Run the two rules over the same target and they disagree on two of the five hosts below.

| Host, with `app.shop.example` as the target | Crawler's rule | Guard at the tool boundary |
|---|---|---|
| `app.shop.example` | in | in |
| `beta.app.shop.example` | in | in |
| `api.shop.example` | out | in |
| `shop.example` | out | in |
| `payments-vendor.example` | out | out |

The crawler will not follow a link to the sibling API host. The tool boundary will run a tool against it without complaint, if something else puts that URL into a tool call. Which answer you get depends on which component happens to be asking, so the literal-host discipline is enforced in this system by whichever check is strictest along a given path rather than by policy.

I would consolidate them, and I have not, and I want to resist describing this as one mechanism with a wrinkle in it. It is two implementations of one idea, written at different times for different callers, agreeing on the easy cases and diverging on precisely the case the discipline exists for. When you build this, write the function once and give every component the same one. I did not, and what that costs is a question with two answers.

## The skip ledger

A host the agent decided not to test is a fact about the engagement, and the deliverable should carry it.

So every host that comes out of discovery and does not get tested is written down with a reason. Out of scope. Dead, parked, or refusing to resolve. Indistinguishable from a host already tested, so testing it twice buys nothing. Over the budget for this run. The ledger is persisted alongside the scan and reported to the operator, and the rule attached to it is that a host is never silently dropped.

The value of that is easiest to see from the receiving end. Handed a report with no ledger, a reader has one interpretation available: everything in the estate was looked at, and this is what came back. Handed a report with a ledger, they can see which hosts were tested, which were ruled out of scope, which were dead, and which came off the end of a budget, and now the conversation is about whether that last group should be paid for next week. Chapter 05 is where this becomes a general argument about reporting what you did not do. Here it is just the natural place to put the reasons a scope function has already computed.

The limit is the familiar one. On the fan-out path, where one scan spreads across many hosts, the ledger is built by the orchestrating agent following a markdown contract and persisted through the analysis store. That is convention, the same species as chapter 01's stage machine and chapter 02's agent-path waist: an instruction that works in practice, enforced by an agent that has generally done what it was told. The skip the executor performs is code and returns a reason. The ledger of hosts is prose that has been reliable so far. Those are different properties, and a report cannot tell them apart.

## The floor

Some things need a human regardless of what any scope declaration says.

Denial of service, load and stress testing. Destructive actions: deleting data, defacing anything, locking accounts out at scale. Supply-chain compromise, and pivoting onto genuinely third-party infrastructure. Evasion techniques whose purpose is evasion.

That list is not a smaller scope. It is a different axis. Scope answers whom you may touch; the floor answers what you may do to them, and an authorised host does not authorise you to take it down or empty its database. The two get conflated constantly, usually by an authorisation letter that grants a domain and says nothing about behaviour, and the conflation is comfortable because it lets everyone skip the harder conversation.

[num-ok 1]
I do not want that list automated, and this is the one place in the handbook where I argue against a function. Whether a load test is acceptable depends on the target being in its quiet window, on whether the environment shares infrastructure with production, on whether the account you are about to lock belongs to a real customer, and on whether somebody is on call. None of those facts are in the system. A function that returned a boolean here would be returning a confident answer to a question it cannot see the inputs for, which is worse than a pause.

What I will not do is dress that up as a control. Nothing in the executor refuses a tool call for being destructive; its only pre-execution refusal is the scope one. The nearest thing in the code is a program-brief mechanism that disables named tools when a bug-bounty programme excludes a class, plus a rate limiter that backs off when the target starts complaining. The rate limiter is politeness. Neither is authorisation. What actually holds the floor is the operator, plus the instructions the orchestrator reads at the start of a run, and I have no measurement of how often either has been tested.

## What the selected run recorded

Everything above is the design. Here is the measurement that went against it.

In the selected public-target aggregate, `1` author-recorded run, `6` of the run's `12` findings were labelled false positives. Chapter 02 quoted that count for a different argument. The repository does not include the raw findings, ground truth or matcher, so neither the labels nor the recorded precision can be independently reproduced from this snapshot. Here is what the author's retained account says is inside the count. Three of the six carry the name of a third-party service in the title, all three from the bundle miner, all three reported as missing-authentication leads. Two of those three are third-party hosts, both IP-geolocation providers, that the miner lifted out of the target's own JavaScript. The third is not a host at all: `/engine.io` is the default path a socket transport library declares for itself, so the name in that row belongs to a path and not to anybody's server. Which of the two shapes the miner picked it up in, the plain path or a protocol-relative form of the same name, the row cannot settle: the join collapses `/api//engine.io` and `/api/engine.io` onto the same URL.

A scoping gap in the author's retained account, not an independently reproducible benchmark finding. Sizing the described failure mode is what the rest of this section does.

Running the miner over a synthetic bundle shows how a host reaches that position. The miner keeps a quoted string when the string starts with a slash, which is a decent test for a path and admits one shape that is not a path: a protocol-relative URL, `//geo.vendor.example/v1/city`, the form that leaves the scheme off and lets the browser fill it in. An absolute URL carrying `https://` is not picked up at all, in either the config-object form or the fetch-call form, and neither is a bare hostname with no leading slash. Whatever survives that filter then has a base prefixed to it, taken from the bundle's own declared API base, or from observed traffic, or from a seed list whose first entry is `/api`. Only the first candidate is probed. The probe URL is that candidate with leading slashes stripped, joined onto the scan target's scheme and host, and it comes out as a request to the target with the vendor's name in the path, which is the shape the retained account describes.

[num-ok 2]
No packet left the target for anybody. All three rows record a request to the target's own host and port, and the two genuine third-party hosts appear inside the path of those requests rather than in front of them. What the run produced is an artifact that names other people's infrastructure in a finding title. That is embarrassing and it is not a trespass.

Two separate things kept those requests on the target, and I first credited the wrong one, in a sentence saying the leading-slash strip was the only reason. Replay the shape the rows actually carry, a protocol-relative host sitting under the `/api` base, and it lands on the target either way: `/api//geo.vendor.example/v1/city` resolves to the target with the strip and to the target without it, because the base in front means the string no longer opens with two slashes and the join has nothing to read as a network-path reference. The base prefix is the guard that fired here. The disconfirming row was sitting in my own replay output, next to the row I generalised from.

The strip is load-bearing in a narrower case: when the candidate reaches the join bare. That case is reachable rather than theoretical. When the run has observed a request whose path matches one the miner recovered, the resolved base comes out empty, the candidate stays `//geo.vendor.example/v1/city`, and with the strip removed the probe resolves to that host instead of the target.

[num-ok 3]
And neither guard applies when the bundle declares its API base as an absolute URL, which the rule that reads those bases accepts. Then the candidate is itself an absolute URL, stripping leading slashes does nothing to a string that opens with a scheme, and the join hands it back unchanged. The probe leaves the target host. So the tidy sentence I wanted, that the miner cannot go off-host, is false. The true one is smaller: a bare protocol-relative candidate is held on the target by one line of string handling, and a declared absolute base is held by nothing at all. How often bundles declare one I have not measured.

And the scope function was not involved in any of it. It runs at the tool boundary, against the target the tool was called with, and the tool in question was called with the target: the in-scope host, correctly admitted. Every probe that tool then fired at a reconstructed endpoint went out without anyone asking the question a second time. The crawler is the one component that asks again, with the narrower rule from three sections back, and the crawler was not in this path. A boolean asked once at the top of a tool does not govern the requests the tool goes on to make.

Generalise it and the shape is this. A scope function is only as good as the point where URLs enter the system, and out-of-scope material does not arrive as an out-of-scope URL. It arrives as a hostname with no scheme, or as a fragment that gets joined onto something later, at a point where the guard sees a URL on the target host and correctly says yes. The check that would have caught this is not admission at the request boundary. It is asking, at the moment a mined string becomes a candidate, whether the thing you just extracted names a host at all.

## What it costs to build this

Someone has to write the scope declaration, and the declaration is exactly as good as the person who typed it. Nothing in this chapter validates that the hosts in the in-scope list are hosts the engagement actually covers. The function converts a declaration into enforcement, faithfully, including when the declaration is wrong.

Registrable-domain admission is generous, and generous by default is a choice with a bill. It makes a bare target work without configuration, which is why it is there, and it means the default posture is wider than the literal-host discipline the operator is actually working to. Narrowing it per engagement is manual, so it happens when someone remembers.

Two implementations of one idea cost more than the duplicated lines. They cost you the ability to answer "is this host in scope" without first asking "according to which component". I have that answer for today's code. Getting it again after the next edit to either rule is somebody's job, and nobody has it.

The ledger costs discipline on the path where it is convention rather than code, and that cost is paid every run, by an agent, out of sight.

And the floor costs you the unattended runs you wanted. A pipeline that stops and asks a human is a pipeline that cannot go home at five, and every improvement anyone proposes to it starts with removing exactly that. I have written the sentence that would automate one of those decisions, more than once, and then not shipped it, and my confidence that this was wisdom rather than luck is lower than I would like.

---

*Theodoros Moutesidis.*

---

## Number annotations

These notes were written inline in the handbook source beside the numbers they explain; the renderer collects them here and leaves a `[num-ok N]` marker at each point of use above.

**[num-ok 1]** one place is a spelled quantity counting a position in this handbook's own argument rather than anything in the code, which is what the sentence itself says it is

**[num-ok 2]** three rows is a spelled quantity counting a code artifact: the three findings this section counts out of the run's reported false positives, each of them described individually above

**[num-ok 3]** one line is a spelled quantity counting a code artifact: the single line of string handling this sentence names, in the bundle miner this repository withholds rather than in core/
