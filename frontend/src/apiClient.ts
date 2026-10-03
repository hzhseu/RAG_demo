// Sequence checks cover both response headers and deferred JSON body reads.
export function createApiClient(token: string, onChanged: () => void, fetcher: typeof fetch = fetch) {
  const scoped = (path: string) => path !== '/status' && !path.startsWith('/knowledge/');
  const modelScoped = (path: string) => path !== '/status' && !path.startsWith('/models') && !path.endsWith('/activate');
  const client = {
    modelSequence: undefined as number | undefined,
    sequence: undefined as number | undefined,
    async request(path: string, init: RequestInit = {}): Promise<Response> {
      const sequence = client.sequence;
      const modelSequence = client.modelSequence;
      const headers = {'X-Nord-Token': token, 'Content-Type': 'application/json',
        ...(modelSequence !== undefined ? {'X-Model-Sequence': String(modelSequence)} : {}),
        ...(sequence !== undefined ? {'X-Knowledge-Sequence': String(sequence)} : {}), ...init.headers};
      const response = await fetcher('/api' + path, {...init, headers});
      if (modelScoped(path) && modelSequence !== client.modelSequence) throw new Error('回答模型已切换，请重试');
      if (scoped(path) && sequence !== client.sequence) throw new Error('知识库已切换，请重试');
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        if (data.code === 'knowledge_changed' || data.code === 'model_changed') onChanged();
        throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`);
      }
      return response;
    },
    async json<T = any>(path: string, init: RequestInit = {}): Promise<T> {
      const sequence = client.sequence;
      const modelSequence = client.modelSequence;
      const response = await client.request(path, init);
      const data = await response.json();
      if (modelScoped(path) && modelSequence !== client.modelSequence) throw new Error('回答模型已切换，请重试');
      if (scoped(path) && sequence !== client.sequence) throw new Error('知识库已切换，请重试');
      return data;
    },
  };
  return client;
}
