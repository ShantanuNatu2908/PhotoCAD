import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Enum
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid() -> str:
    return str(uuid.uuid4())

class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    unit = Column(String(16), default="mm")  # "mm" or "inch"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    scan_sessions = relationship("ScanSession", back_populates="project", cascade="all, delete-orphan")


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    status = Column(String(32), default="capturing")  # capturing, calibrated, processing_cv, fused, failed
    has_scale_reference = Column(Integer, default=0) # 1 if ArUco or calibrated marker present
    scale_px_to_mm = Column(Float, default=1.0)
    calibration_json = Column(JSON, nullable=True)
    geometry_report_json = Column(JSON, nullable=True)
    ply_file = Column(String(256), nullable=True)
    
    # Store paths, masks, blur scores, and summary for all 6 orthogonal views
    views_data = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="scan_sessions")
    generations = relationship("CadGeneration", back_populates="scan_session", cascade="all, delete-orphan")


class CadGeneration(Base):
    __tablename__ = "cad_generations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    scan_session_id = Column(String(36), ForeignKey("scan_sessions.id"), nullable=False)
    version = Column(Integer, default=1)
    status = Column(String(32), default="pending")  # pending, generating, compiling, completed, failed
    
    # Synthesized CAD code (CadQuery or OpenSCAD)
    code = Column(Text, nullable=True)
    
    # File paths for exported assets
    step_file = Column(String(256), nullable=True)
    dxf_file = Column(String(256), nullable=True)
    stl_file = Column(String(256), nullable=True)
    
    # Estimated physical dimensions [X, Y, Z] in mm
    dimensions_mm = Column(JSON, nullable=True)
    
    # Compiler output / Traceback if failed
    error_log = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    scan_session = relationship("ScanSession", back_populates="generations")
    agent_logs = relationship("AgentLog", back_populates="generation", cascade="all, delete-orphan")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    generation_id = Column(String(36), ForeignKey("cad_generations.id"), nullable=False)
    agent_name = Column(String(64), nullable=False)  # e.g., "VisionAnalyst", "CSGArchitect", "CadCoder", "Validator"
    log_type = Column(String(32), default="info")     # info, thought, code, error, success
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    generation = relationship("CadGeneration", back_populates="agent_logs")
