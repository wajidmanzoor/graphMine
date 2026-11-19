import type {components} from "../generated/api";
import type {Transport} from "./client";

export type Domain = components["schemas"]["DomainProfile"];
export type Session = components["schemas"]["SessionRecord"] & {id: string};
export type NodeFactory = <K extends keyof HTMLElementTagNameMap>(tag: K, attributes?: Record<string, string | number | boolean>, text?: string | number) => HTMLElementTagNameMap[K];
export interface HistoryDependencies {
  state: {sessions: Session[]; session: Session | null; domains: Domain[]};
  api: Transport;
  node: NodeFactory;
  notice(message: string, error?: boolean): void;
  onAction(session: Session, action: string): Promise<void>;
}
export interface RenderingDependencies {
  state: {noticeTimer?: number; domains: Domain[]};
  $(id: string): HTMLElement;
  onDomain(domain: Domain): void;
}
declare global {
  interface Window {
    GraphMineRendering(dependencies: RenderingDependencies): {node: NodeFactory; notice(message: string, error?: boolean): void; renderDomains(): void};
    GraphMineSessionHistory(dependencies: HistoryDependencies): {load(append?: boolean): Promise<void>; render(): void};
  }
}
