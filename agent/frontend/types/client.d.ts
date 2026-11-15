import type {paths} from "../generated/api";

type Operation<P extends keyof paths, M extends keyof paths[P]> = NonNullable<paths[P][M]>;
type Parameters<T> = T extends {parameters: infer V} ? V : never;
type PathArguments<T> = Parameters<T> extends {path: infer V} ? {path: V} : {path?: never};
type QueryArguments<T> = Parameters<T> extends {query?: infer V} ? {query?: V} : {query?: never};
type JSONBody<T> = T extends {content: {"application/json": infer V}} ? V : never;
type BodyArguments<T> = T extends {requestBody: infer V} ? {body: JSONBody<V>}
  : T extends {requestBody?: infer V} ? {body?: JSONBody<NonNullable<V>>} : {body?: never};
type ResponseValue<T> = T extends {responses: infer V}
  ? {[K in keyof V]: K extends 200 | 201 | 202 ? JSONBody<V[K]> : K extends 204 ? null : never}[keyof V]
  : unknown;
type Method<P extends keyof paths> = {[M in keyof paths[P]]: [NonNullable<paths[P][M]>] extends [never] ? never : NonNullable<paths[P][M]> extends {responses: unknown} ? M : never}[keyof paths[P]];
export type Arguments<P extends keyof paths, M extends keyof paths[P]> = PathArguments<Operation<P, M>> & QueryArguments<Operation<P, M>> & BodyArguments<Operation<P, M>> & {
  signal?: AbortSignal; headers?: HeadersInit; asBlob?: boolean;
};
export interface Client {
  <P extends keyof paths, M extends Method<P>>(method: M, path: P, args: Arguments<P, M> & {asBlob: true}): Promise<Blob>;
  <P extends keyof paths, M extends Method<P>>(method: M, path: P, args: Arguments<P, M>): Promise<ResponseValue<Operation<P, M>>>;
}
export type Transport = (path: string, options?: RequestInit & {asBlob?: boolean}, busyRetries?: number) => Promise<any>;
