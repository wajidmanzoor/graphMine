import type {Client, Transport} from "./client";

declare global {
  interface Window {
    GraphMineAsync: {
      delay(milliseconds: number, signal?: AbortSignal | null): Promise<undefined>;
      retryAfter(value: string | null): number;
      backoff(failures: number, requested?: number, base?: number): number;
      readScope(options: {api: Transport; signal: AbortSignal; current: () => boolean}): {current(): boolean; get(path: string, retries?: number): Promise<any>};
    };
    GraphMineTransport: ((dependencies: {state: {base: string; token: string}; W: {parse(text: string): any}}) => Transport) & {
      APIError: new (message: string, status: number, code: string | undefined, details: unknown, retryAfter: number) => Error;
    };
    GraphMineClient(api: Transport, wire: {stringify(value: unknown): string}): Client;
  }
}
export {};
