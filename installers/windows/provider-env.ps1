function Set-LesProviderEnvironment {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("mlx", "openrouter", "openai", "ollama", "lemonade", "freetoken", "openai-compatible")]
    [string]$Provider,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$AdapterPort
  )

  if ($Provider -ne "lemonade") { return }

  $adapterUrl = "http://127.0.0.1:$AdapterPort"
  $Environment = @{
    LEMONADE_BASE_URL = "http://127.0.0.1:13305/api/v1"
    LEMONADE_HOST_PORT = [string]$AdapterPort
    MLX_URL = $adapterUrl
    EMBED_URL_PARSE = $adapterUrl
    LEMONADE_EMBED_MODEL = "Qwen3-Embedding-0.6B-GGUF"
    EMBED_MODEL = "Qwen3-Embedding-0.6B-GGUF"
    LES_SMETA_NORM_EMBED_MODEL = "Qwen3-Embedding-0.6B-GGUF"
    EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
    LEMONADE_EMBED_BACKEND = "llama_cpp"
    EMBED_BACKEND = "llama_cpp"
    LES_EMBED_PROFILE = "qwen"
    RAG_VECTOR_SIZE = "1024"
  }
  if ($Environment.ContainsKey('RAG_CHUNK_TOKENS') -or $Environment.ContainsKey('RAG_CHUNK_OVERLAP')) {
    throw 'provider mapping must not own the persisted index chunk contract'
  }
  foreach ($item in $Environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable(
      [string]$item.Key,
      [string]$item.Value,
      [EnvironmentVariableTarget]::Process
    )
  }
}

function Set-LesLemonadeEmbeddingEnvironment {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$AdapterPort
  )

  Set-LesProviderEnvironment -Provider "lemonade" -AdapterPort $AdapterPort
}
