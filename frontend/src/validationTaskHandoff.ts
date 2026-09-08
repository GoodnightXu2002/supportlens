type RunnerCommandInput = {
  baseUrl: string
  taskId: string
  runnerToken: string
}

function powerShellLiteral(value: string) {
  return `'${value.replaceAll("'", "''")}'`
}

export function buildLocalRunnerCommand({
  baseUrl,
  taskId,
  runnerToken,
}: RunnerCommandInput) {
  return [
    `$env:SUPPORTLENS_BASE_URL=${powerShellLiteral(baseUrl)}`,
    `$env:RUNNER_TASK_ID=${powerShellLiteral(taskId)}`,
    `$env:RUNNER_TOKEN=${powerShellLiteral(runnerToken)}`,
    "$env:AGENT_ENDPOINT='<YOUR_OPENAI_COMPATIBLE_ENDPOINT>'",
    "$env:AGENT_API_KEY='<YOUR_LOCAL_AGENT_API_KEY>'",
    "$env:AGENT_MODEL='<YOUR_CANDIDATE_MODEL>'",
    'uv run python -m app.local_runner',
  ].join('\n')
}

export function withValidationTaskId(search: string, taskId: string) {
  const params = new URLSearchParams(search)
  params.set('validation_task_id', taskId)
  params.delete('runner_token')
  return params
}
