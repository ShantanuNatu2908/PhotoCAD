import React, { useEffect, useRef } from 'react';
import { Terminal, CheckCircle2, AlertTriangle, Cpu, Code2, Sparkles } from 'lucide-react';
import type { AgentLog } from '../types/cad';

interface AgentTerminalProps {
  logs: AgentLog[];
  status: string;
}

export const AgentTerminal: React.FC<AgentTerminalProps> = ({ logs, status }) => {
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const getAgentBadge = (agent: string) => {
    switch (agent) {
      case 'VisionAnalyst':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700">Vision Analyst</span>;
      case 'CSGArchitect':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300 border border-purple-700">CSG Architect</span>;
      case 'CadCoder':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-300 border border-amber-700">Cad Coder</span>;
      case 'Validator':
        return <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-300 border border-emerald-700">Self-Healing Validator</span>;
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
      case 'error':
        return <AlertTriangle className="w-3.5 h-3.5 text-rose-400 mt-0.5 shrink-0" />;
      case 'success':
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />;
      default:
        return <Cpu className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />;
    }
  };

  return (
    <div className="flex flex-col h-full bg-cad-card border border-cad-border rounded-xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="bg-cad-dark px-4 py-2.5 border-b border-cad-border flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-mono font-semibold tracking-wide text-slate-200">
            Multi-Agent Reasoning Stream
          </span>
        </div>
        <div className="flex items-center space-x-2">
          <span className={`w-2 h-2 rounded-full ${status === 'completed' ? 'bg-emerald-400' : status === 'generating' || status === 'compiling' ? 'bg-cyan-400 animate-ping' : 'bg-slate-500'}`} />
          <span className="text-[11px] font-mono uppercase text-slate-400">{status}</span>
        </div>
      </div>

      {/* Terminal Output */}
      <div className="flex-1 p-4 font-mono text-xs overflow-y-auto space-y-3 bg-[#080b11]">
        {logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center space-y-2 py-8">
            <Cpu className="w-8 h-8 text-slate-600 animate-pulse" />
            <p>Agent loop idle. Upload 6-axis photos and click "Synthesize 3D CAD" to engage.</p>
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
