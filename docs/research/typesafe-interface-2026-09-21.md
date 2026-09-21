# TypeSafe System One / Jev interface for FuseBench CP-05

Checked 2026-09-21 against TypeSafe's official documentation, official Python SDK repository, and official PyPI release metadata. No live evaluation call was made.

Local verification found `typesafe-sdk` 0.7.0 installed in `.venv`; the same version and official wheel hash are recorded in [`uv.lock`](../../uv.lock). Its exported names, call signatures, constants, question serialization, and Pydantic response fields matched the pinned 0.7.0 official source cited below. This inspection did not send a network request.

## Current interface

### Endpoint, authentication, and package

- Evaluation endpoint: `POST https://api.typesafe.ai/v1/systemone`.
- Authentication: `Authorization: Bearer <API_KEY>`.
- JSON request body: `state`, `model`, and a nonempty `questions` map.
- Official Python distribution: `typesafe-sdk`; import module: `typesafe_sdk`.
- Current public Python SDK release: `0.7.0` (released 2026-09-18), requiring Python 3.10 or newer.
- SDK defaults: `TYPESAFE_API_KEY`, base URL `https://api.typesafe.ai`, model `jev-latest`, and a 10-second per-operation timeout. Explicit constructor arguments override environment values.

Sources: [HTTP API reference](https://docs.typesafe.ai/api), [Python SDK quickstart](https://docs.typesafe.ai/sdk/python), [PyPI 0.7.0](https://pypi.org/project/typesafe-sdk/0.7.0/), [pinned SDK constants](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/constants.py), and [pinned SDK transport](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/_core/transport.py).

### Model alias and concrete version

The current concrete model is `jev-1.13.0`. `jev-latest` currently resolves to it, as does `jev-preview`. An alias can move when a new release ships, so the answers behind `jev-latest` can change without a code change. The response's `model` field reports the versioned model that actually answered. Official docs explicitly state that a concrete version such as `jev-1.13.0` is accepted in the request even when `GET /v1/models` lists only aliases.

For a reproducible benchmark run, use `jev-1.13.0` and record every response's `model`. `jev-latest` remains appropriate for exploratory development where automatic upgrades are wanted.

Source: [official Models reference](https://docs.typesafe.ai/models).

### Python request shape

The synchronous API is `TypeSafeClient.system_one(state, questions, *, model=None, retry=None, timeout=None, extra_headers=None, extra_body=None, response_model=None)`. `AsyncTypeSafeClient` provides the asynchronous equivalent.

```python
from typesafe_sdk import Choice, Noul, NoulCriteria, Score, TypeSafeClient

with TypeSafeClient(api_key=api_key, model="jev-1.13.0", timeout=30.0) as client:
    response = client.system_one(
        state={"message": "I was charged twice. Please help today."},
        questions={
            "route": Choice(
                instructions="Which team should handle this?",
                criteria={
                    "billing": "Payments, invoices, and refunds",
                    "technical": "Bugs and integrations",
                },
            ),
            "refund_requested": Noul(
                instructions="Does the message request a refund?",
                criteria=NoulCriteria(
                    true="The customer asks for money to be returned",
                    false="No refund is requested",
                ),
            ),
            "urgency": Score(
                instructions="How urgently should this be handled?",
                criteria=["Can wait", "This week", "Today"],
            ),
        },
    )
```

`state` is a top-level string, object, or array. `Choice.criteria` maps labels to string/object/array descriptions or `None`. `Noul.criteria` optionally describes `true` and `false`. `Score.criteria` is an ordered sequence of level descriptions; its index is the level number. Raw question dictionaries with an explicit `type` discriminator are also accepted.

Sources: [sync client reference](https://docs.typesafe.ai/sdk/python/api/clients/sync), [questions reference](https://docs.typesafe.ai/sdk/python/api/types/questions), [pinned client source](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/_core/client/sync/client.py), and [pinned question types](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/_core/question_types.py).

### Same-state batching

One request evaluates one shared `state` against one or more independent questions. Choice, Noul, and Score questions can be mixed in the same map. TypeSafe recommends putting all questions that share state into one request: the questions are evaluated independently and in parallel, and the shared state is sent only once. There is no documented multi-state batch operation in Python SDK 0.7.0; different states require separate calls.

Sources: [State](https://docs.typesafe.ai/concepts/state), [Primitives](https://docs.typesafe.ai/primitives), [Speculative fan-out](https://docs.typesafe.ai/patterns/fan-out), and [Parallel questions cookbook](https://docs.typesafe.ai/cookbooks/parallel_questions).

### Response and answer fields

The response contains:

- `model`: concrete model identifier that answered.
- `answers`: mapping keyed by the request's question IDs.
- `usage`: token counts.

Each answer includes a matching `type` discriminator:

- Noul: `type`, `noul`. `noul` is the probability of yes in `[0, 1]`; there is no separate confidence field.
- Choice: `type`, `choice`, `probabilities`, `confidence`. `choice` is the highest-probability label. `confidence` is a statistic derived from the shape of the distribution, not the probability of the selected label.
- Score: `type`, `score`, `legend`, `probabilities`, `confidence`. `score` is the probability-weighted expected level and can be fractional. The wire format uses string keys for `legend` and `probabilities`; the Python SDK converts those keys to integers.

The SDK exposes `response.answers[id]` and filtered views `response.nouls`, `response.choices`, and `response.scores`. `response.request_id` reads the `x-typesafe-request-id` header, and `response.raw_http_response` exposes the underlying status, headers, and body. SDK 0.7.0 responses are frozen Pydantic models; use `model_dump()` or `model_dump_json()` when serialization is needed.

Sources: [HTTP response schema](https://docs.typesafe.ai/api), [Python answers and responses](https://docs.typesafe.ai/sdk/python/api/types/responses), [Confidence](https://docs.typesafe.ai/confidence), [pinned response implementation](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/_core/response_types.py), and [SDK changelog](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/docs/changelog.md).

### Usage and pricing

The response usage object reports `input_tokens` and `output_tokens`. The HTTP reference presents both as required integers; the Python SDK types each as `int | None` for forward/backward compatibility.

Current Jev pricing is `$42` per billion input tokens, equivalent to `$0.042` per million input tokens. Output tokens are free. FuseBench's estimate is therefore correct:

```python
jev_cost_usd = input_tokens * 42 / 1_000_000_000
```

Source: [official Models reference](https://docs.typesafe.ai/models).

## Drift and CP-05 implications

- Pin `typesafe-sdk==0.7.0` for the frozen environment. Version 0.6 changed `Score.criteria` from an integer-keyed mapping to an ordered sequence; version 0.7 changed response models from `msgspec` to Pydantic. [Official changelog](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/docs/changelog.md).
- Pin `jev-1.13.0` for primary benchmark runs. If `jev-latest` is used during development, persist and compare `response.model`; aborting on a mid-run concrete-version change is consistent with the official alias semantics.
- Always supply nonempty `instructions` and two to ten Score levels. The HTTP documentation calls instructions required and specifies two to ten Score levels, while SDK 0.7.0 permits omitted instructions and its local validation rejects only an empty Score list. Treat the stricter public API guidance as the contract. [HTTP API](https://docs.typesafe.ai/api), [SDK question validation](https://github.com/typesafe-ai/typesafe-sdk-python/blob/2ce5c65f13646cab6e6f782328194c9d85f3300a/src/typesafe_sdk/_core/questions.py).
- Do not manufacture missing usage. Because SDK fields permit `None`, CP-05 should fail closed or mark cost/accounting unresolved if `input_tokens` is absent.
- Batch all information-need questions that see the same initial state into one call, and all terminal-decision questions that see the same terminal state into their own call. Do not combine questions that require different states.
- Record both full probabilities and TypeSafe `confidence`, but use the selected Choice probability for FuseBench's cross-system probability metric. Noul's `noul` value is both its yes probability and the value to threshold.
- Treat published batching speed/cost multiples as illustrative, not contractual. The current cookbook reports 12.2x cheaper and 10.0x faster for its fixed example, while the Primitives page still says 11.5x and 9.6x. The stable interface claim is that same-state questions are independent and can be evaluated together.
- TypeSafe describes Jev as text-only, meaning no image/audio/video input. Its SDK and examples nevertheless support ordinary structured JSON state, including nested numeric, boolean, and null values. Keep CP-05 state JSON-serializable and avoid binary/media payloads.
- Pricing, rate limits, and alias targets are mutable service facts. Capture this research date, package lock, requested model, reported model, raw usage, and calculated cost with the run artifacts.

## CP-05 compatibility conclusion

The FuseBench CP-05 assumptions about endpoint, Bearer authentication, imports, Choice/Noul/Score fields, same-state batching, usage fields, and the input-token cost formula match the current official TypeSafe interface. The material implementation constraints are to use the SDK 0.7.0 Pydantic response objects, pass Score criteria as an ordered list, handle optional usage counts explicitly, and pin the concrete `jev-1.13.0` model for the primary benchmark.
