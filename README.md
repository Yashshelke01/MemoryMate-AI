# 🧠 MemoryMate AI

### Your Personal AI Memory Assistant — Powered by FalkorDB

MemoryMate AI is an AI-powered personal memory assistant designed to help users store, organize, connect, and retrieve information through persistent, graph-based memory.

Unlike traditional systems that treat information as isolated records, MemoryMate AI uses graph database technology to represent relationships between pieces of information. This graph-based approach helps the application retrieve relevant context and connect related memories.

**Hackathon:** Graph Hacks — FalkorDB Hackathon 2026
**Recommended Track:** Agent Memory and Coordination — verify the official track name when submitting.
**Repository:** https://github.com/Yashshelke01/MemoryMate-AI

---

## 📌 Table of Contents

* [Problem Statement](#-problem-statement)
* [Our Solution](#-our-solution)
* [Key Features](#-key-features)
* [Why FalkorDB](#-why-falkordb)
* [Technology Stack](#-technology-stack)
* [System Architecture](#-system-architecture)
* [Graph Data Model](#-graph-data-model)
* [Cypher Queries and Graph Algorithms](#-cypher-queries-and-graph-algorithms)
* [Project Structure](#-project-structure)
* [Getting Started](#-getting-started)
* [Configuration](#-configuration)
* [Running the Application](#-running-the-application)
* [API Documentation](#-api-documentation)
* [Testing](#-testing)
* [Demo Video](#-demo-video)
* [Deployment](#-deployment)
* [Security and Privacy](#-security-and-privacy)
* [Team](#-team)
* [AI Assistance Disclosure](#-ai-assistance-disclosure)
* [Future Improvements](#-future-improvements)
* [License](#-license)

---

## 🎯 Problem Statement

People accumulate information across conversations, projects, notes, and everyday interactions. However, retrieving a specific fact later can be difficult.

Traditional storage approaches often treat each memory as an isolated record. This makes it harder to discover meaningful connections between related information.

A useful personal memory assistant should be able to:

* Preserve information across interactions.
* Retrieve previously stored information.
* Connect related memories.
* Provide relevant context when answering questions.
* Keep users' information appropriately separated.

## 💡 Our Solution

MemoryMate AI combines a web-based interface, a Python backend, graph-based memory storage, and relational data storage.

The application uses FalkorDB to represent connected information as a graph and SQLite for relational application data.

Its graph-based memory layer is intended to help retrieve information based not only on individual stored items but also on relationships between them.

The goal is to make personal information easier to preserve, connect, and retrieve.

---

## ✨ Key Features

### 🧠 Personal Memory Management

Store and retrieve information through the application's memory functionality.

### 🕸️ Graph-Based Memory

Represent related information using graph nodes and relationships in FalkorDB.

### 🔎 Contextual Retrieval

Use the graph memory and retrieval services to find information relevant to a user's query.

### 💬 Conversational Interface

Interact with the application through its web-based chat interface.

### 🗂️ Conversation Management

Support conversation history and related operations through the backend API.

### 🔐 Authentication

Provide backend authentication functionality, subject to the application's current configuration.

### 🌐 Web Interface

Use a browser-based interface built with HTML, CSS, and JavaScript.

### 🧪 Automated Tests

Include tests for backend services, API behavior, and graph-related functionality.

> Feature availability depends on the configured services and the current implementation. Consult the code and setup instructions before relying on optional functionality.

---

## 🚀 Why FalkorDB?

FalkorDB is a graph database designed for storing and querying connected data.

MemoryMate AI uses FalkorDB as its graph memory store.

Graph databases represent information through nodes, relationships, and properties. This allows an application to query connections between pieces of information rather than treating every item as completely independent.

For a personal memory assistant, graph storage can support:

* Representing relationships between memories and entities.
* Traversing connected information.
* Retrieving related context.
* Exploring how stored information is connected.
* Building more sophisticated memory retrieval workflows.

FalkorDB supports Cypher-style graph queries, allowing graph operations to be expressed declaratively.

**FalkorDB is a core part of MemoryMate AI's graph memory architecture, not simply a visualization tool.**

---

## 🛠️ Technology Stack

| Component            | Technology                | Purpose                                  |
| -------------------- | ------------------------- | ---------------------------------------- |
| Backend              | Python                    | Application logic                        |
| API Framework        | FastAPI                   | HTTP API endpoints                       |
| Graph Database       | FalkorDB                  | Graph-based memory storage and retrieval |
| Relational Database  | SQLite                    | Relational application data              |
| Frontend             | HTML                      | Application structure                    |
| Styling              | CSS                       | User interface design                    |
| Frontend Logic       | JavaScript                | Browser-side behavior                    |
| Testing              | pytest                    | Automated testing                        |
| Graph Query Language | Cypher-compatible queries | Graph operations                         |

---

## 🏗️ System Architecture

```text
                  ┌─────────────────────────┐
                  │         User            │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │   Web Frontend          │
                  │   HTML, CSS, JavaScript │
                  └────────────┬────────────┘
                               │ HTTP Requests
                               ▼
                  ┌─────────────────────────┐
                  │     FastAPI Backend     │
                  │                         │
                  │  API Routes             │
                  │  Authentication         │
                  │  Conversation Services  │
                  │  Memory Services        │
                  │  Retrieval Services     │
                  └───────────┬─────────────┘
                              │
                  ┌───────────┴────────────┐
                  │                        │
                  ▼                        ▼
       ┌──────────────────┐     ┌──────────────────┐
       │     FalkorDB     │     │      SQLite      │
       │                  │     │                  │
       │ Graph Memory     │     │ Relational Data  │
       │ Nodes            │     │ Application Data │
       │ Relationships    │     │                  │
       │ Graph Queries    │     │                  │
       └──────────────────┘     └──────────────────┘
```

### Request Flow

1. The user interacts with the web interface.
2. The frontend sends an HTTP request to the FastAPI backend.
3. The backend validates and processes the request.
4. Relevant application services interact with FalkorDB, SQLite, or other configured services.
5. The backend processes the results.
6. The frontend displays the response.

The exact sequence depends on the endpoint and operation being performed.

---

## 🕸️ Graph Data Model

The graph data model is an important part of MemoryMate AI because it defines how information is represented and connected.

### Graph Components

A graph database typically contains three fundamental elements:

| Element       | Description                                             |
| ------------- | ------------------------------------------------------- |
| Nodes         | Represent entities or stored information                |
| Relationships | Connect nodes and represent associations                |
| Properties    | Store attributes associated with nodes or relationships |

### Illustrative Memory Model

The following is an illustrative model for explaining graph-based memory. **It is not a verified schema of the current implementation. Replace it with the actual labels, relationships, and properties used by the source code.**

```text
(:User)-[:HAS_MEMORY]->(:Memory)

(:Memory)-[:RELATED_TO]->(:Memory)

(:Memory)-[:MENTIONS]->(:Entity)
```

Possible interpretations:

* `User`: Represents a user.
* `Memory`: Represents a stored memory.
* `Entity`: Represents a person, project, concept, or other identifiable subject.
* `HAS_MEMORY`: Connects a user to a memory.
* `RELATED_TO`: Connects related memories.
* `MENTIONS`: Connects a memory to an entity.

The actual graph schema must be documented using the implementation in `graph_memory_db/` and `backend/app/db/`.

### Example Concept

Imagine a user stores the following information:

* "I am building MemoryMate AI."
* "MemoryMate AI uses FastAPI."
* "MemoryMate AI uses FalkorDB."

A graph representation could connect the project to its technologies.

```text
            ┌────────────────┐
            │ MemoryMate AI  │
            └───────┬────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
     ┌─────────┐         ┌─────────┐
     │ FastAPI │         │FalkorDB │
     └─────────┘         └─────────┘
```

This illustrates the concept of connected information. It does not establish that these exact nodes and relationships are currently created by the application.

### User Isolation

The application should ensure that users can access only the memories they are authorized to access.

Document the actual implementation's user-isolation strategy, including how graph queries scope reads and writes to the correct user.

---

## 🔍 Cypher Queries and Graph Algorithms

Graph queries are central to the graph memory layer.

The repository contains graph-related implementation files:

* `graph_memory_db/falkordb_client.py`
* `graph_memory_db/graph_queries.py`
* `graph_memory_db/memory_service.py`
* `graph_memory_db/retrieval_service.py`
* `backend/app/db/falkordb_client.py`
* `backend/app/db/graph_queries.py`

### Required Query Documentation

The actual Cypher queries used by MemoryMate AI should be documented in a dedicated file:

**[`docs/GRAPH_MODEL_AND_QUERIES.md`](docs/GRAPH_MODEL_AND_QUERIES.md)**

That document should describe:

1. Memory creation and storage.
2. Graph node and relationship creation.
3. Memory retrieval.
4. Relationship traversal.
5. User-scoped graph operations.
6. Any graph algorithms the application actually implements.

For each query, document its purpose, the labels and relationships it uses, and how the returned data contributes to memory retrieval.

**Important:** The documentation file must be added to the repository before claiming that this deliverable is complete.

Do not substitute illustrative Cypher queries for the real queries executed by the application.

---

## 📁 Project Structure

```text
MemoryMate-AI/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── auth.py
│   │   │       ├── chat.py
│   │   │       ├── conversations.py
│   │   │       ├── graph.py
│   │   │       ├── health.py
│   │   │       └── memories.py
│   │   ├── db/
│   │   │   ├── falkordb_client.py
│   │   │   ├── graph_queries.py
│   │   │   └── sqlite_store.py
│   │   ├── models/
│   │   ├── services/
│   │   ├── config.py
│   │   ├── container.py
│   │   └── main.py
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── README.md
│
├── frontend/
│   ├── assets/
│   ├── css/
│   ├── js/
│   ├── index.html
│   └── README.md
│
├── graph_memory_db/
│   ├── falkordb_client.py
│   ├── graph_queries.py
│   ├── memory_service.py
│   └── retrieval_service.py
│
├── docs/
│   └── GRAPH_MODEL_AND_QUERIES.md
│
├── PROJECT_CONTRACT.md
├── .gitignore
└── README.md
```

---

## ⚙️ Getting Started

### Prerequisites

Before running the project, prepare:

* Git.
* A compatible Python version.
* A running FalkorDB instance.
* A modern web browser.
* Any optional LLM provider credentials required by your configuration.

Check `backend/requirements.txt` and `backend/README.md` for project-specific requirements.

### 1. Clone the Repository

```bash
git clone https://github.com/Yashshelke01/MemoryMate-AI.git
cd MemoryMate-AI
```

### 2. Create a Python Virtual Environment

From the project root:

```powershell
cd backend
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use an appropriate local execution-policy setting or invoke the virtual environment's Python executable directly.

### 3. Install Dependencies

```powershell
python -m pip install -r requirements.txt
```

For development and testing dependencies, consult `requirements-dev.txt`.

### 4. Configure Environment Variables

Copy the provided environment template:

```powershell
Copy-Item .env.example .env
```

Open `backend/.env` and set the values required by the application.

The exact variables and their accepted values are defined by the configuration implementation and `backend/.env.example`.

Do not publish your actual `.env` file or any credentials.

### 5. Start FalkorDB

Start a FalkorDB instance using the deployment method supported by your environment.

For local development, Docker may be an option if Docker is installed and your configuration supports it.

Ensure that:

* The FalkorDB service is running.
* The backend's configured host and port match the service.
* Authentication settings are consistent.
* The graph database is accessible from the backend.

Consult your actual configuration before selecting connection settings or ports.

### 6. Start the Backend

From the `backend` directory, follow the startup command specified in `backend/README.md`.

For example, if the application exposes the FastAPI instance as `app.main:app`, a development server can be started with:

```powershell
python -m uvicorn app.main:app --reload
```

Use this command only if it matches the project's actual entry point and installed dependencies.

### 7. Start the Frontend

Open `frontend/README.md` and follow its instructions.

Ensure that the frontend's configured API base URL points to the running backend.

If the frontend is served separately, configure the backend's CORS settings appropriately.

---

## 🔧 Configuration

MemoryMate AI uses environment-based configuration.

The application may require settings for:

* FalkorDB connection details.
* SQLite database location.
* API configuration.
* Authentication.
* Optional LLM provider integration.
* Frontend-to-backend communication.

Use `backend/.env.example` as the source of truth for the variable names supported by the current implementation.

Never commit real API keys, passwords, tokens, or database credentials.

---

## 🌐 API Documentation

MemoryMate AI includes FastAPI routes for application operations.

The backend route files include:

| Route module       | Purpose                   |
| ------------------ | ------------------------- |
| `auth.py`          | Authentication operations |
| `chat.py`          | Chat operations           |
| `conversations.py` | Conversation management   |
| `graph.py`         | Graph-related operations  |
| `health.py`        | Health checks             |
| `memories.py`      | Memory operations         |

The actual endpoints, HTTP methods, request schemas, and response schemas are defined in the source code.

When the backend is running, FastAPI's interactive API documentation is commonly available at:

```text
http://localhost:8000/docs
```

Use this address only if the backend is configured to run on port `8000` and its OpenAPI documentation is enabled.

---

## 🧪 Testing

The repository includes automated tests for core application behavior.

From the `backend` directory, activate the virtual environment and run:

```powershell
python -m pytest
```

Tests that require an external FalkorDB instance or optional integrations may need additional configuration.

Review test output and document any prerequisites for the graph-related tests.

---

## 🎥 Demo Video

**Demo video:** Replace this line with your actual publicly accessible demo video URL.

The demo should show the working application and explain the role of FalkorDB.

### Suggested Demo Flow

1. Introduce MemoryMate AI and the problem it solves.
2. Show the web interface.
3. Store a sample memory.
4. Ask a question about the stored information.
5. Demonstrate the retrieved result.
6. Show relevant graph nodes, relationships, or query results.
7. Explain how the graph supports memory retrieval.
8. Briefly describe the system architecture.

Record and publish a demonstration of the actual implementation. Do not present planned functionality as if it were already working.

---

## 🚀 Deployment

MemoryMate AI can be evaluated using either a live deployment or a complete local setup.

### Local Evaluation

For local evaluation:

1. Clone the repository.
2. Install the backend dependencies.
3. Configure environment variables.
4. Start FalkorDB.
5. Start the backend.
6. Start or open the frontend according to its documentation.
7. Test memory creation and retrieval.

### Production Deployment

A production deployment should provide:

* A reachable backend API.
* A persistent and accessible FalkorDB instance.
* Persistent SQLite storage or a suitable alternative for the deployment architecture.
* Secure environment-variable management.
* Appropriate authentication and access controls.
* Correct frontend API configuration.
* Monitoring and error handling.

Do not claim that the application is deployed until a working deployment has been tested.

---

## 🔐 Security and Privacy

MemoryMate AI handles information that users may consider personal.

Security considerations include:

* Keeping API keys and passwords out of source control.
* Enforcing user authorization on memory operations.
* Preventing cross-user data access.
* Protecting database credentials.
* Avoiding unnecessary logging of sensitive content.
* Using appropriate authentication and transport security in production.

The repository's `.gitignore` excludes local environment files and database artifacts from normal Git staging.

Security-sensitive functionality should be reviewed and tested before production use.

---

## 👥 Team

**Team Name:** The Celestials

MemoryMate AI was developed as a team project for the FalkorDB graph database hackathon.

Add the names and contributions of all four team members here before submission.

| Team Member | Contribution                              |
| ----------- | ----------------------------------------- |
| Member 1    | Replace with actual name and contribution |
| Member 2    | Replace with actual name and contribution |
| Member 3    | Replace with actual name and contribution |
| Member 4    | Replace with actual name and contribution |

---

## 🤖 AI Assistance Disclosure

AI coding assistance was used during development for activities such as technical guidance, debugging support, code review, and documentation.

The team is responsible for reviewing, testing, understanding, and explaining the submitted implementation.

Update this disclosure to accurately reflect the tools and assistance used by the team.

---

## 🔮 Future Improvements

Potential future improvements include:

* More advanced semantic memory retrieval.
* Improved relationship discovery between memories.
* Graph visualization and exploration.
* Additional LLM provider integrations.
* Better memory ranking and relevance evaluation.
* More comprehensive integration testing.
* Production deployment and monitoring.
* Enhanced user controls for memory retention and deletion.

These are potential improvements and should not be interpreted as currently implemented features.

---

## 📄 License

No license has been specified for this project yet.

Unless a license is added, the project remains subject to the default applicable copyright rules. Add an appropriate license if you intend to grant others explicit rights to use, modify, and redistribute the source code.

---

## ⭐ Acknowledgements

Thanks to the Graph Hacks community and FalkorDB ecosystem for encouraging developers to explore graph-based applications and connected-data systems.

If you find the project interesting, consider starring the repository and sharing feedback.
