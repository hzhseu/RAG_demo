import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApiClient} from '../src/apiClient.ts';

test('rejects an old knowledge body that completes after a switch', async () => {
  let finish;
  const body = new ReadableStream({start(controller) {finish = () => {
    controller.enqueue(new TextEncoder().encode('{"messages":["old library"]}'));
    controller.close();
  };}});
  const client = createApiClient('test', () => {}, async () => new Response(body));
  client.sequence = 1;
  const pending = client.json('/sessions/abc');
  await new Promise(resolve => setImmediate(resolve));
  client.sequence = 2;
  finish();
  await assert.rejects(pending, /知识库已切换/);
});

test('sends sequence and token and refreshes on a server conflict', async () => {
  let changed = 0;
  const client = createApiClient('test', () => changed++, async (url, init) => {
    assert.equal(init.headers['X-Knowledge-Sequence'], '4');
    assert.equal(init.headers['X-Nord-Token'], 'test');
    return Response.json({code:'knowledge_changed', detail:'知识库已切换'}, {status:409});
  });
  client.sequence = 4;
  await assert.rejects(client.json('/documents'), /知识库已切换/);
  assert.equal(changed, 1);
});

test('a successful switch is not rejected when status polling already sees it', async () => {
  const client = createApiClient('test', () => {}, async () => {
    client.sequence = 3;
    return Response.json({cancelled:false, sequence:3});
  });
  client.sequence = 2;
  assert.equal((await client.json('/knowledge/switch', {method:'POST'})).sequence, 3);
});
