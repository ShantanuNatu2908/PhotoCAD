import React, { useEffect, useRef } from 'react';
import { Terminal, CheckCircle2, AlertTriangle, Cpu, Code2, Sparkles, GitCompare } from 'lucide-react';
import type { AgentLog, ValidationMetrics } from '../types/cad';

interface AgentTerminalProps {
  logs: AgentLog[];
  status: string;
  activeNode?: string | null;
  validationMetrics?: ValidationMetrics | null;
}

const LANGGRAPH_NODES = [
  { id: 'geometry_analyst', label: '1. Analyst' },
  { id: 'parametric_architect', label: '2. Architect' },
  { id: 'cad_synthesizer', label: '3. Synthesizer' },
  { id: 'sandbox_executor', label: '4. Sandbox' },
  { id: 'geometric_validator', label: '5. Validator' },
];

export const AgentTerminal: React.FC<AgentTerminalProps> = ({
  logs,
  status,
  activeNode,
  validationMetrics,
}) => {
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const getAgentBadge = (agent: string) => {
    switch (agent) {
      case 'VisionAnalyst':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700">1. Geometry Analyst</span>;
      case 'CSGArchitect':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300 border border-purple-700">2. Parametric Architect</span>;
      case 'CadCoder':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-300 border border-amber-700">3. build123d Synthesizer</span>;
      case 'SandboxExecutor':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-indigo-900/60 text-indigo-300 border border-indigo-700">4. Sandbox Executor</span>;
      case 'Validator':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-300 border border-emerald-700">5. Chamfer Validator</span>;
      default:
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">{agent}</span>;
    }
  };

  const getLogIcon = (type: string) => {
    switch (type) {
      case 'thought':
        return <Sparkles className="w-3.5 h-3.5 text-cyan-400 mt-0.5 shrink-0" />;
      case 'code':
        return <Code2 className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />;
      case 'diff':
        return <GitCompare className="w-3.5 h-3.5 text-cyan-300 mt-0.5 shrink-0" />;
      case 'error':
        return <AlertTriangle className="w-3.5 h-3.5 text-rose-400 mt-0.5 shrink-0" />;
      case 'success':
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />;
      default:
        return <Cpu className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />;
    }
  };

  const renderDiffBlock = (diffText: string) => {
    const lines = diffText.split('\n');
    return (
      <pre className="p-2 rounded bg-black/75 border border-slate-800 text-[11px] w-full overflow-x-auto font-mono leading-snug">
        {lines.map((line, i) => {
          const cls = line.startsWith('+')
            ? 'text-emerald-300'
            : line.startsWith('-')
            ? 'text-rose-300'
            : line.startsWith('@@')
            ? 'text-cyan-400'
            : 'text-slate-400';
          return (
            <div key={i} className={cls}>
              {line}
            </div>
          );
        })}
      </pre>
    );
  };

  return (
    <div className="flex flex-col h-full bg-cad-card border border-cad-border rounded-xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="bg-cad-dark px-4 py-2 border-b border-cad-border flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-mono font-semibold tracking-wide text-slate-200">
            LangGraph Dual-Loop Stream
          </span>
        </div>

        <div className="flex items-center space-x-3">
          {validationMetrics && (
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                validationMetrics.passed_tolerance
                  ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700'
                  : 'bg-amber-950/70 text-amber-300 border-amber-700'
              }`}
            >
              Chamfer {validationMetrics.chamfer_mean_mm.toFixed(2)}mm • {validationMetrics.is_watertight ? 'Watertight' : 'Open'}
            </span>
          )}
          <div className="flex items-center space-x-2">
            <span className={`w-2 h-2 rounded-full ${status === 'completed' ? 'bg-emerald-400' : status === 'generating' || status === 'compiling' ? 'bg-cyan-400 animate-ping' : 'bg-slate-500'}`} />
            <span className="text-[11px] font-mono uppercase text-slate-400">{status}</span>
          </div>
        </div>
      </div>

      {/* 5-Node Stepper Pill Row */}
      <div className="bg-[#0b1018] px-3 py-1.5 border-b border-cad-border flex items-center justify-between gap-1 overflow-x-auto">
        {LANGGRAPH_NODES.map((node) => {
          const isCurrent = activeNode === node.id;
          return (
            <div
              key={node.id}
              className={`px-2 py-0.5 rounded text-[10px] font-mono whitespace-nowrap border transition ${
                isCurrent
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 font-bold animate-pulse'
                  : status === 'completed'
                  ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/50'
                  : 'bg-cad-dark/60 text-slate-500 border-cad-border/50'
              }`}
            >
              {node.label}
            </div>
          );
        })}
      </div>

      {/* Terminal Output */}
      <div className="flex-1 p-4 font-mono text-xs overflow-y-auto space-y-3 bg-[#080b11]">
        {logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center space-y-2 py-8">
            <Cpu className="w-8 h-8 text-slate-600 animate-pulse" />
            <p>LangGraph state machine idle. Run 3D Fusion then click &quot;Synthesize 3D CAD&quot;.</p>
          </div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="space-y-1 bg-cad-dark/50 p-2.5 rounded border border-slate-800/80">
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <div className="flex items-center space-x-2">
                  {getAgentBadge(log.agent_name)}
                  <span className="text-slate-500">{new Date(log.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
              <div className="flex items-start space-x-2 pt-1 text-slate-300 leading-relaxed">
                {getLogIcon(log.log_type)}
                {log.log_type === 'code' ? (
                  <pre className="p-2 rounded bg-black/60 border border-slate-800 text-[11px] text-emerald-300 w-full overflow-x-auto whitespace-pre font-mono">
                    {log.message}
                  </pre>
                ) : log.log_type === 'diff' ? (
                  renderDiffBlock(log.message)
                ) : (
                  <p className="flex-1">{log.message}</p>
                )}
              </div>
            </div>
          ))
        )}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
};
