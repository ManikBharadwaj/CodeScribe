# CodeScribe: Secure Code Vault & Static AST Analysis Platform

**Academic Context:** 5th Semester B.Tech Computer Science & Engineering (3rd Year) Minor Project  
**Institution:** Department of Computer Science & Engineering  

---

## Team Members
* **Manik Sharma** (Project Owner & Backend Architecture)
* **Pushkar Sharma** (Static Analysis Engine & AST Parser)
* **Vaishali Bhardwaj** (Authentication & Session Security)
* **Atul Sharma** (Frontend Integration & UI/UX Workbench)

---

## 1. Project Overview & Objectives
**CodeScribe** is a web-based code management and static analysis platform designed to help student developers and engineers organize source code into isolated workspaces, perform static code analysis safely without runtime execution, and track code quality metrics (such as Cyclomatic Complexity, lines of code, function counts, and control structures).

The application is built around a modern Single Page Application (SPA) architecture utilizing a Flask RESTful backend paired with a responsive dark-mode frontend, secure user authentication, relational database storage via SQLAlchemy, and built-in Abstract Syntax Tree (AST) parsing for Python and structural token analysis for C++.

---

## 2. System Architecture & Tech Stack

```
CODESCRIBE/
├── app.py              # Flask server, REST API endpoints, session auth & error handling
├── models.py           # SQLAlchemy ORM models (User, Workspace, CodeFile)
├── analyzer.py         # Static analysis engine (Python AST NodeVisitor & C++ tokenizer)
├── requirements.txt    # Python dependencies (Flask, Flask-SQLAlchemy, Werkzeug)
├── smoke_test.py       # Automated test suite (30 end-to-end integration tests)
├── instance/
│   └── codescribe.db   # SQLite relational database (auto-generated)
├── static/
│   ├── style.css       # Responsive dark-mode stylesheet & dashboard layout
│   └── script.js       # SPA client controller (Fetch API, auth, workspace & editor UI)
└── templates/
    └── index.html      # Main HTML interface (auth cards & code analysis workbench)
```

### Technology Stack
* **Backend Framework:** Python 3.13, Flask 3.1 (REST API, application factory pattern)
* **Database & ORM:** SQLite / PostgreSQL compatible via Flask-SQLAlchemy 3.1
* **Security & Cryptography:** Werkzeug security utilities (PBKDF2-HMAC-SHA256 password hashing, secure session cookies)
* **Static Analysis:** Python built-in `ast` module (`NodeVisitor` design pattern) & Regular Expression structural parsing for C++
* **Frontend:** HTML5, CSS3 (CSS Grid, responsive media queries), Vanilla JavaScript (ES6+ asynchronous Fetch API)

---

## 3. Core Features & Implementation Details

### A. Authentication & Session Security (`app.py`, `models.py`)
* **User Registration (`/api/auth/register`):** Validates email format, enforces password length (minimum 8 characters) and matching confirmation, hashes passwords securely using `generate_password_hash`, and automatically provisions a default workspace ("Main Workspace") for new users.
* **Authentication (`/api/auth/login` & `/logout`):** Authenticates credentials using `check_password_hash` and maintains encrypted server-side session cookies (`session["user_id"]`).
* **Resource Ownership Authorization:** All workspace and file routes enforce rigorous user isolation. If a user attempts to query, modify, or delete a workspace or file belonging to another user, the system halts execution and returns an HTTP `403 Forbidden` response.

### B. Relational Database Schema (`models.py`)
1. **`User` Model:** Stores user credentials (`id`, `full_name`, `email` [unique index], `password_hash`, `created_at`). Has a one-to-many relationship with `Workspace`.
2. **`Workspace` Model:** Groups code files logically per user (`id`, `name`, `description`, `user_id` [FK], `created_at`). Configured with cascade deletion (`cascade="all, delete-orphan"`).
3. **`CodeFile` Model:** Stores source code files (`id`, `name`, `language`, `content`, `workspace_id` [FK], `created_at`).

### C. Static Code Analysis Engine (`analyzer.py`)
* **Python AST Analysis:** Rather than executing untrusted user code via dangerous constructs like `exec()` or subprocesses, CodeScribe parses Python source code into an Abstract Syntax Tree using `ast.parse()`. A custom `ast.NodeVisitor` subclass (`PythonASTVisitor`) traverses nodes to count:
  * Functions (`ast.FunctionDef`, `ast.AsyncFunctionDef`)
  * Loops (`ast.For`, `ast.AsyncFor`, `ast.While`)
  * Conditionals (`ast.If`, `ast.IfExp`)
  * Classes (`ast.ClassDef`) and Imports
  * **Cyclomatic Complexity:** Computed deterministically as $1 + \text{decision points}$ (branching nodes and boolean operators).
  * **Syntax Validation:** Catches `SyntaxError` exceptions gracefully, reporting exact line numbers, character offsets, and snippets.
* **C++ Structural Analysis:** Employs regex-based pattern matching to inspect C++ source code files for function signatures, control loops (`for`, `while`, `do`), conditional branching (`if`, `switch`), and header inclusions (`#include`).

---

## 4. Setup & Execution Guide

### Prerequisites
* Python 3.10 or higher installed on your system.

### Step 1: Clone or Open Project
Open a terminal in the project root directory:
```bash
cd path/to/CODESCRIBE
```

### Step 2: Install Dependencies
Install required Python packages via `pip`:
```bash
python -m pip install -r requirements.txt
```

### Step 3: Run Automated Smoke Tests
Verify all database models, authentication flows, ownership checks, and AST analysis rules by running the integration test suite:
```bash
python smoke_test.py
```
*(All 30 automated integration tests pass successfully with 100% coverage).*

### Step 4: Run the Flask Development Server
Start the application server locally:
```bash
python app.py
```

### Step 5: Access the Application
Open your web browser and navigate to:
```text
http://127.0.0.1:5000
```
* Register a new student/developer account.
* Use the **Code Workbench** to write or upload Python / C++ source files.
* Click **Analyze AST** to inspect real-time complexity metrics and syntax validation reports.

---

## 5. Limitations, Security Notes & Future Scope

### Current Limitations
* **File Size & Types:** Optimized for source files under 2MB restricted to `.py`, `.cpp`, `.h`, and `.hpp` extensions.
* **C++ Analysis Scope:** C++ analysis relies on structural token scanning rather than a full C++ Clang AST parser.

### Security Guarantees
* **No Code Execution:** Source code is inspected purely via static analysis (`ast.parse`); user code is never compiled or executed on the server, eliminating Remote Code Execution (RCE) vectors.
* **SQL Injection Prevention:** All database queries are managed exclusively through SQLAlchemy ORM parameterization.
* **Access Control:** Strict session checks and foreign-key ownership enforcement prevent IDOR vulnerabilities.

### Future Scope (Phase 2)
* Migration from SQLite to managed PostgreSQL for enterprise deployment.
* Integration of AST visualization graphs (dependency trees and control-flow graphs using D3.js).
* Role-based access control (RBAC) for collaborative team code review workspaces.
