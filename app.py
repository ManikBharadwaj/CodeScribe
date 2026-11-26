"""
CodeScribe Backend Application
Flask REST API server handling authentication, workspace management, file uploads,
and Python/C++ AST static code analysis.
"""

from datetime import datetime, timezone
import os

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from analyzer import analyze_code
from models import CodeFile, User, Workspace, db
from runner import RunnerBusy, RunnerUnavailable, run_code

# Allowed code file extensions
ALLOWED_EXTENSIONS = {"py", "cpp", "h", "hpp"}
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB Limit
SUPPORTED_LANGUAGES = {
    "python": "python", "py": "python",
    "cpp": "cpp", "c++": "cpp", "c": "cpp",
    "h": "cpp", "hpp": "cpp"
}


def create_app():
    """Application factory for configuring Flask and database."""
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Security configuration
    app.secret_key = os.environ.get("SECRET_KEY", "codescribe-dev-secret-key-2026")
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_BYTES + 64 * 1024

    # Database configuration (SQLite default, PostgreSQL compatible)
    db_url = os.environ.get("DATABASE_URL", "sqlite:///codescribe.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize extensions
    db.init_app(app)

    with app.app_context():
        # Ensure database tables exist
        db.create_all()

    # Register Error Handlers
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": str(e.description) if hasattr(e, "description") else "Bad request"}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Authentication required. Please log in."}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Access denied. You do not own this resource."}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found."}), 404

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "An unexpected server error occurred."}), 500

    @app.errorhandler(413)
    def request_too_large(e):
        return jsonify({"error": "Request exceeds the 2MB code limit."}), 413

    # Helper functions
    def get_current_user():
        """Retrieve logged in User model instance or None."""
        user_id = session.get("user_id")
        if not user_id:
            return None
        return db.session.get(User, user_id)

    def allowed_file(filename):
        """Check if uploaded filename has an allowed extension."""
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    # -------------------------------------------------------------------
    # Page Route
    # -------------------------------------------------------------------
    @app.route("/")
    def index():
        """Serve main SPA HTML interface."""
        return render_template("index.html")

    # -------------------------------------------------------------------
    # Block 1: Health Check Endpoint
    # -------------------------------------------------------------------
    @app.route("/api/health", methods=["GET"])
    def health_check():
        """Returns API health status and UTC timestamp."""
        return jsonify({
            "status": "ok",
            "service": "CodeScribe API",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200

    # -------------------------------------------------------------------
    # Block 3: Authentication Routes
    # -------------------------------------------------------------------
    @app.route("/api/auth/register", methods=["POST"])
    def register():
        """Registers a new user account with hashed password and default workspace."""
        data = request.get_json() or {}
        full_name = (data.get("full_name") or data.get("fullName") or "").strip()
        email = (data.get("email") or data.get("registerEmail") or "").strip().lower()
        password = data.get("password") or data.get("registerPassword") or ""
        confirm_password = data.get("confirm_password") or data.get("confirmPassword") or ""

        if not full_name:
            return jsonify({"error": "Full name is required."}), 400

        if not email or "@" not in email:
            return jsonify({"error": "A valid email address is required."}), 400

        if not password or len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters long."}), 400

        if password != confirm_password:
            return jsonify({"error": "Passwords do not match."}), 400

        # Check existing user
        if db.session.query(User).filter_by(email=email).first():
            return jsonify({"error": "An account with this email address already exists."}), 400

        # Create user & hashed password
        hashed_pw = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(full_name=full_name, email=email, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        # Create initial default workspace for convenience
        default_workspace = Workspace(
            name="Main Workspace",
            description="Default CodeScribe project space",
            user_id=new_user.id
        )
        db.session.add(default_workspace)
        db.session.commit()

        # Log in user automatically via session
        session["user_id"] = new_user.id

        return jsonify({
            "message": "Account created successfully!",
            "user": new_user.to_dict(),
            "default_workspace_id": default_workspace.id
        }), 201

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        """Authenticates user email/password and starts a session."""
        data = request.get_json() or {}
        email = (data.get("email") or data.get("loginEmail") or "").strip().lower()
        password = data.get("password") or data.get("loginPassword") or ""

        if not email or not password:
            return jsonify({"error": "Email and password are required."}), 400

        user = db.session.query(User).filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid email or password."}), 401

        session["user_id"] = user.id

        return jsonify({
            "message": "Login successful!",
            "user": user.to_dict()
        }), 200

    @app.route("/api/auth/logout", methods=["POST"])
    def logout():
        """Clears user session."""
        session.clear()
        return jsonify({"message": "Logged out successfully."}), 200

    @app.route("/api/auth/me", methods=["GET"])
    def current_user_info():
        """Returns currently authenticated user profile."""
        user = get_current_user()
        if not user:
            return jsonify({"authenticated": False}), 401

        return jsonify({
            "authenticated": True,
            "user": user.to_dict()
        }), 200

    # -------------------------------------------------------------------
    # Block 3: Workspace Routes (User Ownership Protected)
    # -------------------------------------------------------------------
    @app.route("/api/workspaces", methods=["GET"])
    def list_workspaces():
        """Returns list of workspaces owned by the logged-in user."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        workspaces = Workspace.query.filter_by(user_id=user.id).order_by(Workspace.created_at.desc()).all()
        return jsonify({"workspaces": [w.to_dict() for w in workspaces]}), 200

    @app.route("/api/workspaces", methods=["POST"])
    def create_workspace():
        """Creates a new workspace for the logged-in user."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()

        if not name:
            return jsonify({"error": "Workspace name is required."}), 400

        workspace = Workspace(name=name, description=description, user_id=user.id)
        db.session.add(workspace)
        db.session.commit()

        return jsonify({
            "message": "Workspace created successfully.",
            "workspace": workspace.to_dict()
        }), 201

    @app.route("/api/workspaces/<int:workspace_id>", methods=["GET"])
    def get_workspace(workspace_id):
        """Retrieves workspace details and file list for owned workspace."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        workspace = db.session.get(Workspace, workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace not found."}), 404

        if workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this workspace."}), 403

        return jsonify({"workspace": workspace.to_dict(include_files=True)}), 200

    @app.route("/api/workspaces/<int:workspace_id>", methods=["DELETE"])
    def delete_workspace(workspace_id):
        """Deletes an owned workspace and all associated files."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        workspace = db.session.get(Workspace, workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace not found."}), 404

        if workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this workspace."}), 403

        db.session.delete(workspace)
        db.session.commit()

        return jsonify({"message": "Workspace deleted successfully."}), 200

    # -------------------------------------------------------------------
    # Block 4: Code File Upload & Management
    # -------------------------------------------------------------------
    @app.route("/api/workspaces/<int:workspace_id>/files", methods=["POST"])
    def add_file_to_workspace(workspace_id):
        """
        Accepts code file upload via raw JSON content OR multipart form data,
        stores in database, and runs initial AST/structural analysis.
        """
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        workspace = db.session.get(Workspace, workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace not found."}), 404

        if workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this workspace."}), 403

        filename = ""
        content = ""
        language = "python"

        # Check if multipart form upload or JSON
        if request.files and "file" in request.files:
            file_obj = request.files["file"]
            raw_filename = file_obj.filename or "script.py"

            if not allowed_file(raw_filename):
                return jsonify({
                    "error": f"Invalid file type. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                }), 400

            filename = secure_filename(raw_filename)
            if not filename or filename.startswith("."):
                return jsonify({"error": "Invalid filename format."}), 400
            if len(filename) > 100:
                return jsonify({"error": "File name must be 100 characters or fewer."}), 400
            content_bytes = file_obj.read()

            if len(content_bytes) > MAX_FILE_SIZE_BYTES:
                return jsonify({"error": "File size exceeds 2MB limit."}), 400

            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return jsonify({"error": "File must be valid UTF-8 text."}), 400

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "py"
            language = "cpp" if ext in ("cpp", "h", "hpp") else "python"

        else:
            # Handle JSON body payload
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                return jsonify({"error": "Request body must be a JSON object."}), 400
            raw_filename = data.get("name")
            content = data.get("content", "")

            if not isinstance(raw_filename, str) or not raw_filename.strip():
                return jsonify({"error": "File name is required."}), 400
            raw_filename = raw_filename.strip()
            if not isinstance(content, str):
                return jsonify({"error": "File content must be text."}), 400

            filename = secure_filename(raw_filename)
            if not filename or filename.startswith("."):
                return jsonify({"error": "Invalid filename format."}), 400
            if len(filename) > 100:
                return jsonify({"error": "File name must be 100 characters or fewer."}), 400

            if not allowed_file(filename):
                return jsonify({
                    "error": f"Disallowed extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                }), 400

            extension = filename.rsplit(".", 1)[-1].lower()
            inferred_language = "cpp" if extension in ("cpp", "h", "hpp") else "python"
            requested_language = data.get("language")
            if requested_language is None:
                language = inferred_language
            elif not isinstance(requested_language, str) or requested_language.lower() not in SUPPORTED_LANGUAGES:
                return jsonify({"error": "Unsupported language. Use Python or C++."}), 400
            else:
                language = SUPPORTED_LANGUAGES[requested_language.lower()]
                if language != inferred_language:
                    return jsonify({"error": "File extension and selected language do not match."}), 400

            try:
                content_size = len(content.encode("utf-8"))
            except UnicodeEncodeError:
                return jsonify({"error": "File content must be valid UTF-8 text."}), 400
            if content_size > MAX_FILE_SIZE_BYTES:
                return jsonify({"error": "File content exceeds 2MB limit."}), 400

        # Save file to DB
        code_file = CodeFile(
            name=filename,
            language=language,
            content=content,
            workspace_id=workspace.id
        )
        db.session.add(code_file)
        db.session.commit()

        # Run static analysis engine
        analysis = analyze_code(content, language=language)

        return jsonify({
            "message": "File created and analyzed successfully.",
            "file": code_file.to_dict(include_content=True),
            "analysis": analysis
        }), 201

    @app.route("/api/files/<int:file_id>", methods=["GET"])
    def get_file(file_id):
        """Retrieves a single code file and its static analysis."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        code_file = db.session.get(CodeFile, file_id)
        if not code_file:
            return jsonify({"error": "File not found."}), 404

        if code_file.workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this file."}), 403

        analysis = analyze_code(code_file.content, language=code_file.language)

        return jsonify({
            "file": code_file.to_dict(include_content=True),
            "analysis": analysis
        }), 200

    @app.route("/api/files/<int:file_id>", methods=["PUT"])
    def update_file(file_id):
        """Updates an owned code file and returns fresh static analysis."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        code_file = db.session.get(CodeFile, file_id)
        if not code_file:
            return jsonify({"error": "File not found."}), 404

        if code_file.workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this file."}), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400

        raw_filename = data.get("name", code_file.name)
        content = data.get("content", code_file.content)
        requested_language = data.get("language", code_file.language)
        if not isinstance(raw_filename, str) or not raw_filename.strip():
            return jsonify({"error": "File name is required."}), 400
        if not isinstance(content, str):
            return jsonify({"error": "File content must be text."}), 400
        if not isinstance(requested_language, str) or requested_language.lower() not in SUPPORTED_LANGUAGES:
            return jsonify({"error": "Unsupported language. Use Python or C++."}), 400

        filename = secure_filename(raw_filename.strip())
        if not filename or filename.startswith(".") or not allowed_file(filename):
            return jsonify({
                "error": f"Invalid file name. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            }), 400
        if len(filename) > 100:
            return jsonify({"error": "File name must be 100 characters or fewer."}), 400

        extension = filename.rsplit(".", 1)[-1].lower()
        inferred_language = "cpp" if extension in ("cpp", "h", "hpp") else "python"
        language = SUPPORTED_LANGUAGES[requested_language.lower()]
        if language != inferred_language:
            return jsonify({"error": "File extension and selected language do not match."}), 400

        try:
            if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
                return jsonify({"error": "File content exceeds 2MB limit."}), 400
        except UnicodeEncodeError:
            return jsonify({"error": "File content must be valid UTF-8 text."}), 400

        code_file.name = filename
        code_file.language = language
        code_file.content = content
        db.session.commit()
        analysis = analyze_code(content, language=language)

        return jsonify({
            "message": "File updated and analyzed successfully.",
            "file": code_file.to_dict(include_content=True),
            "analysis": analysis
        }), 200

    @app.route("/api/files/<int:file_id>", methods=["DELETE"])
    def delete_file(file_id):
        """Deletes a code file."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        code_file = db.session.get(CodeFile, file_id)
        if not code_file:
            return jsonify({"error": "File not found."}), 404

        if code_file.workspace.user_id != user.id:
            return jsonify({"error": "Access denied to this file."}), 403

        db.session.delete(code_file)
        db.session.commit()

        return jsonify({"message": "File deleted successfully."}), 200

    # -------------------------------------------------------------------
    # Block 4: AST Static Analysis Route
    # -------------------------------------------------------------------
    @app.route("/api/analyze-raw", methods=["POST"])
    def analyze_raw():
        """
        Runs Python AST / C++ structural analysis on raw code snippets
        without requiring file persistence.
        """
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        code_string = data.get("content") or data.get("code") or ""
        if not isinstance(code_string, str):
            return jsonify({"error": "Code content must be text."}), 400
        requested_language = data.get("language") or "python"
        if not isinstance(requested_language, str) or requested_language.lower() not in SUPPORTED_LANGUAGES:
            return jsonify({"error": "Unsupported language. Use Python or C++."}), 400
        language = SUPPORTED_LANGUAGES[requested_language.lower()]

        if not code_string.strip():
            return jsonify({"error": "Code content is empty."}), 400

        try:
            if len(code_string.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
                return jsonify({"error": "Code content exceeds 2MB limit."}), 413
        except UnicodeEncodeError:
            return jsonify({"error": "Code content must be valid UTF-8 text."}), 400

        analysis_result = analyze_code(code_string, language=language)
        return jsonify(analysis_result), 200

    # -------------------------------------------------------------------
    # Block 5: Isolated Code Execution
    # -------------------------------------------------------------------
    @app.route("/api/run", methods=["POST"])
    def run_source_code():
        """Runs a Python or C++ submission in the configured Docker sandbox."""
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400

        language = data.get("language")
        code = data.get("code")
        stdin = data.get("stdin", "")
        if language not in ("python", "cpp"):
            return jsonify({"error": "Unsupported language. Use Python or C++."}), 400
        if not isinstance(code, str):
            return jsonify({"error": "Code content must be text."}), 400
        if not isinstance(stdin, str):
            return jsonify({"error": "Standard input must be text."}), 400

        try:
            result = run_code(language, code, stdin)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except RunnerBusy as error:
            return jsonify({"error": str(error)}), 429
        except RunnerUnavailable as error:
            return jsonify({"error": str(error)}), 503

        return jsonify({
            "status": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "execution_time_ms": result.execution_time_ms
        }), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
