\# 🧠 MemoryMate AI



\*\*An AI-powered personal memory assistant that helps you store, connect, and retrieve information using graph-based memory.\*\*



MemoryMate AI is designed to help users preserve useful information, manage conversations, and retrieve relevant memories when needed. It combines a web interface, a Python backend, graph-based memory storage, and relational storage for user information.



\## ✨ Features



\* \*\*Personal Memory:\*\* Store and retrieve information through a dedicated memory system.

\* \*\*Graph-Based Memory:\*\* Use FalkorDB to represent relationships between memories.

\* \*\*Intelligent Retrieval:\*\* Retrieve relevant information from stored memories.

\* \*\*Chat Interface:\*\* Interact with your memory assistant through a web interface.

\* \*\*Conversation Management:\*\* Organize and access conversation history.

\* \*\*Authentication:\*\* Backend authentication functionality.

\* \*\*Memory Management:\*\* Access and manage stored memories.

\* \*\*REST API:\*\* Backend endpoints for application functionality.

\* \*\*Testing:\*\* Automated tests for core services and API behavior.



\## 🛠️ Technology Stack



| Component          | Technology            |

| ------------------ | --------------------- |

| Backend            | Python, FastAPI       |

| Graph Database     | FalkorDB              |

| Relational Storage | SQLite                |

| Frontend           | HTML, CSS, JavaScript |

| API                | REST                  |

| Testing            | pytest                |



\## 🏗️ Project Structure



```text

MemoryMate-AI/

├── backend/

│   ├── app/

│   │   ├── api/

│   │   │   └── routes/

│   │   ├── db/

│   │   ├── models/

│   │   ├── services/

│   │   └── main.py

│   ├── tests/

│   ├── .env.example

│   ├── requirements.txt

│   └── README.md

├── frontend/

│   ├── assets/

│   ├── css/

│   ├── js/

│   └── index.html

├── graph\_memory\_db/

├── PROJECT\_CONTRACT.md

├── .gitignore

└── README.md

```



\## ⚙️ Getting Started



\### Prerequisites



Install or prepare the following:



\* Python compatible with the project's dependencies.

\* Git.

\* A running FalkorDB instance.

\* A modern web browser.



\### 1. Clone the repository



```bash

git clone https://github.com/Yashshelke01/MemoryMate-AI.git

cd MemoryMate-AI

```



\### 2. Set up the backend



Open a terminal in the project directory:



```powershell

cd backend

python -m venv .venv

```



Activate the virtual environment on Windows PowerShell:



```powershell

.\\.venv\\Scripts\\Activate.ps1

```



Install the dependencies:



```powershell

python -m pip install -r requirements.txt

```



\### 3. Configure environment variables



Create your local environment file using the example:



```powershell

Copy-Item .env.example .env

```



Open `backend/.env` and configure the required values for your environment, including FalkorDB connection details and any optional LLM provider settings.



\*\*Never commit your `.env` file, API keys, passwords, or other credentials.\*\*



\### 4. Start the backend



Follow the backend-specific instructions in \[`backend/README.md`](backend/README.md) to configure and start the application.



\### 5. Open the frontend



Follow \[`frontend/README.md`](frontend/README.md) for frontend setup and API configuration.



\## 🧪 Testing



From the `backend` directory, activate your virtual environment and run:



```powershell

python -m pytest

```



Some tests may require additional services or configuration. Follow the test instructions in the backend documentation.



\## 🗄️ Data Storage



MemoryMate AI uses two storage technologies:



\* \*\*FalkorDB:\*\* Graph-oriented storage for memory relationships and graph retrieval.

\* \*\*SQLite:\*\* Relational storage for application data.



The graph database service must be configured and available for features that depend on FalkorDB.



\## 🔐 Security



\* Environment files and local database files are excluded through `.gitignore`.

\* Use `.env.example` as a configuration template.

\* Do not publish credentials, private keys, or personal database contents.

\* Configure authentication and database access appropriately before deploying publicly.



\## 🚀 Future Improvements



Potential improvements include:



\* Production deployment.

\* More advanced semantic memory retrieval.

\* Improved memory visualization.

\* Additional LLM integrations.

\* Enhanced monitoring and testing.



\## 📄 License



No license has been specified yet. Until a license is added, assume the project is protected by the default applicable copyright rules.



