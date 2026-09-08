import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildLocalRunnerCommand,
  withValidationTaskId,
} from '../src/validationTaskHandoff.ts'

test('runner handoff keeps the task id in the URL but never the token', () => {
  const params = withValidationTaskId(
    '?target_id=target-1&runner_token=old-secret',
    'task-1',
  )
  assert.equal(params.get('target_id'), 'target-1')
  assert.equal(params.get('validation_task_id'), 'task-1')
  assert.equal(params.has('runner_token'), false)

  const command = buildLocalRunnerCommand({
    baseUrl: "http://localhost:8000/team's-api",
    taskId: 'task-1',
    runnerToken: 'one-time-token',
  })
  assert.match(command, /SUPPORTLENS_BASE_URL='http:\/\/localhost:8000\/team''s-api'/)
  assert.match(command, /RUNNER_TASK_ID='task-1'/)
  assert.match(command, /RUNNER_TOKEN='one-time-token'/)
  assert.match(command, /uv run python -m app\.local_runner/)
  assert.equal(params.toString().includes('one-time-token'), false)
})
