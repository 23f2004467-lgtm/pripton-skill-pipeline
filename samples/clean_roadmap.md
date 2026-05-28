# Backend Web Development Roadmap

A structured learning path for becoming a backend web developer. Topics are
grouped by area and progress roughly from foundational to advanced. Each
section lists the core concepts a learner should master before moving on.

## Internet Fundamentals

Before writing any backend code, learners need a working mental model of how
the web actually works.

- **How the Internet Works.** The TCP/IP stack, packet routing, DNS lookups,
  the journey of a request from browser to server and back.
- **HTTP and HTTPS.** Methods (GET, POST, PUT, DELETE, PATCH), status codes
  (2xx, 3xx, 4xx, 5xx), headers, request/response lifecycle, the difference
  between HTTP/1.1, HTTP/2, and HTTP/3.
- **Browsers.** What a browser does with a response — parsing, rendering, the
  request/response cycle from the client side.
- **Hosting.** DNS, domain registration, TLS certificates, what a hosting
  provider actually provides.

## Programming Language Foundations

Pick one language and learn it well before sampling others. Common backend
choices: Python, Go, Java, Node.js, Ruby, C#, Rust.

- **Syntax and Control Flow.** Variables, conditionals, loops, functions,
  scoping rules.
- **Data Structures.** Arrays, lists, sets, maps/dictionaries, stacks, queues,
  trees. Understanding which structure to reach for in which situation.
- **Object-Oriented Programming.** Classes, objects, inheritance, polymorphism,
  encapsulation. Even in languages that aren't purely OOP, the concepts inform
  good code organization.
- **Functional Programming Concepts.** Immutability, pure functions, map/filter/
  reduce, higher-order functions. Modern backend code blends FP and OOP idioms.
- **Error Handling.** Exceptions, error returns, when to catch versus when to
  let it propagate.

## Version Control

Version control is not optional for any serious development work.

- **Git.** Branches, commits, merges, rebases, pull requests, resolving conflicts.
- **Remote Repositories.** GitHub, GitLab, Bitbucket — pushing, pulling, code
  review workflows.
- **Workflows.** Trunk-based development, Git Flow, feature branches. Understanding
  which workflow fits which team size.

## Databases

Backend development without a database is rare. Learners should be comfortable
with both relational and non-relational models.

- **Relational Databases.** SQL fundamentals — SELECT, INSERT, UPDATE, DELETE,
  JOINs, GROUP BY, aggregation. PostgreSQL and MySQL are the most common.
- **NoSQL Databases.** Key-value stores (Redis), document stores (MongoDB),
  wide-column stores (Cassandra), graph databases (Neo4j). Understanding when
  each shape fits.
- **Database Design.** Normalization, primary keys, foreign keys, indexes,
  query plans, the cost of joins.
- **ORMs.** Object-relational mappers like SQLAlchemy, Hibernate, Sequelize.
  When they help and when they get in the way.
- **Transactions.** ACID properties, isolation levels, deadlocks, optimistic
  versus pessimistic locking.

## APIs

Most backend code exists to expose or consume APIs.

- **REST.** Resource-oriented design, HTTP verbs mapped to operations, status
  codes, content negotiation, idempotency.
- **GraphQL.** Schema definition, queries, mutations, resolvers, the n+1
  problem, when GraphQL fits and when REST is simpler.
- **gRPC.** Protocol buffers, RPC semantics, streaming, when binary protocols
  win over JSON.
- **API Documentation.** OpenAPI/Swagger, generating client libraries from
  schemas, keeping docs in sync with code.

## Authentication and Authorization

Most APIs need to know who's calling and what they're allowed to do.

- **Authentication Patterns.** Session-based, token-based (JWT), OAuth 2.0,
  OpenID Connect, API keys, mutual TLS.
- **Password Storage.** Hashing with bcrypt or argon2, salts, why fast hashes
  like SHA-256 are wrong for passwords.
- **Authorization Models.** Role-based access control (RBAC), attribute-based
  access control (ABAC), policy engines.

## Caching

Caching is one of the highest-leverage tools for improving backend performance.

- **In-Memory Caches.** Redis, Memcached. TTLs, eviction policies, cache
  invalidation strategies.
- **CDN Caching.** Edge caching, cache headers, surrogate keys.
- **Application-Level Caching.** Memoization, query result caches, the
  cache-aside and read-through patterns.

## Testing

Untested backend code is technical debt waiting to compound.

- **Unit Testing.** Testing individual functions in isolation. Mocking and
  faking external dependencies.
- **Integration Testing.** Testing how components work together — database,
  cache, external services.
- **End-to-End Testing.** Exercising the full system through its public API.
- **Test Doubles.** Stubs, mocks, fakes, spies — and when to use each.
- **Property-Based Testing.** Generating inputs to find edge cases your
  example-based tests miss.

## Containerization and Deployment

Modern backend deployment almost always involves containers.

- **Docker.** Images, containers, Dockerfiles, layers, multi-stage builds.
- **Container Orchestration.** Kubernetes, ECS, Nomad. Pods, deployments,
  services, ingress.
- **CI/CD Pipelines.** Continuous integration with GitHub Actions, GitLab CI,
  Jenkins. Build, test, deploy stages.
- **Cloud Providers.** AWS, GCP, Azure — the core compute, storage, and
  networking primitives each one offers.

## Observability

You can't operate what you can't observe.

- **Structured Logging.** Why JSON logs win over freeform strings, log levels,
  correlation IDs.
- **Metrics.** Prometheus, StatsD, OpenTelemetry. Counters, gauges, histograms,
  RED and USE methods for what to measure.
- **Distributed Tracing.** Spans, traces, propagation across service boundaries.
- **Alerting.** SLOs, error budgets, when to page versus when to ticket.

## Scalability and Reliability

Once a system has users, scale and reliability become the dominant concerns.

- **Horizontal vs Vertical Scaling.** When to add machines versus when to make
  them bigger.
- **Load Balancing.** Round-robin, least-connections, consistent hashing.
- **Message Queues.** Kafka, RabbitMQ, SQS. When to introduce asynchrony.
- **Failure Modes.** Circuit breakers, retries with backoff, timeouts,
  bulkheads, graceful degradation.
- **Disaster Recovery.** Backups, restore drills, RTO and RPO targets.

## Security

Security cuts across every layer above.

- **Common Vulnerabilities.** SQL injection, XSS, CSRF, SSRF, the OWASP Top 10.
- **Transport Security.** TLS, certificate management, HSTS.
- **Secrets Management.** Environment variables versus secret managers,
  rotation, the principle of least privilege.
- **Dependency Security.** Scanning for known vulnerabilities, supply-chain
  attacks, lockfile discipline.
