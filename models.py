"""
CodeScribe Database Models
Flask-SQLAlchemy schema defining User, Workspace, and CodeFile models.
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    """User account model for authentication and workspace ownership."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workspaces = db.relationship(
        "Workspace", backref="owner", cascade="all, delete-orphan", lazy=True
    )

    def to_dict(self):
        """Serialize user object without sensitive data."""
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Workspace(db.Model):
    """Workspace container for grouping code files per user."""
    __tablename__ = "workspaces"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    files = db.relationship(
        "CodeFile", backref="workspace", cascade="all, delete-orphan", lazy=True
    )

    def to_dict(self, include_files=False):
        """Serialize workspace object."""
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "user_id": self.user_id,
            "file_count": len(self.files),
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_files:
            data["files"] = [f.to_dict() for f in self.files]
        return data


class CodeFile(db.Model):
    """Code file stored within a workspace for analysis."""
    __tablename__ = "code_files"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    language = db.Column(db.String(20), nullable=False)  # 'python' or 'cpp'
    content = db.Column(db.Text, nullable=False)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self, include_content=True):
        """Serialize code file object."""
        data = {
            "id": self.id,
            "name": self.name,
            "language": self.language,
            "workspace_id": self.workspace_id,
            "size_bytes": len(self.content.encode("utf-8")),
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_content:
            data["content"] = self.content
        return data
