# Retrieval Evaluation — flask

Gold set: 30 queries · Refusal set: 10 queries

## Overall

- Recall@k:  **0.933**
- MRR:       **0.639**
- Refusal rate (off-topic queries correctly refused): **100%**
- Latency (p50 / p95): **5.95s / 7.61s**

## By category

| Category | N | Recall@k | MRR |
|---|---|---|---|
| conceptual           | 6 | 1.000 | 0.708 |
| cross_reference      | 6 | 1.000 | 0.722 |
| identifier_lookup    | 6 | 0.833 | 0.394 |
| symbol_summary       | 6 | 0.833 | 0.597 |
| usage_example        | 6 | 1.000 | 0.774 |

## Misses (2 of 30)

- **where is dispatch_request defined?** _(cat: identifier_lookup)_
  - expected: `['flask.app.Flask.dispatch_request']`
  - retrieved top-5: `['flask.views', 'tests.type_check.typing_route.RenderTemplateView.dispatch_request', 'flask.views.View.dispatch_request']…`
- **explain url_for** _(cat: symbol_summary)_
  - expected: `['flask.helpers.url_for']`
  - retrieved top-5: `['tests.test_helpers.TestUrlFor', 'tests.test_helpers.TestUrlFor.test_url_for_with_anchor', 'flask.app.Flask.url_for']…`

## Refusal set

| Query | Refused | Top rerank |
|---|---|---|
| How do I configure Django's MIDDLEWARE for CSRF? | ✓ | 0.005 |
| What's the weather forecast for Tokyo tomorrow? | ✓ | 0.000 |
| How does CUDA memory allocation work in PyTorch? | ✓ | 0.000 |
| Show me the React useState hook documentation | ✓ | 0.000 |
| What is the syntax for SQL JOIN clauses? | ✓ | 0.001 |
| How do I deploy a Rust binary to Kubernetes? | ✓ | 0.000 |
| Explain quantum entanglement | ✓ | 0.000 |
| What is the best ice cream flavor? | ✓ | 0.000 |
| How do I write a useEffect cleanup in React? | ✓ | 0.000 |
| Compare TensorFlow and JAX for training transformers | ✓ | 0.000 |
