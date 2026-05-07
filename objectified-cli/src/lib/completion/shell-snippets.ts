/** Shell glue that shells out to `objectified completion candidates` (newline-separated words on stdin). */

export function bashCompletionBody(bin: string): string {
  return `_${bin}_completion() {
  local cur=\${COMP_WORDS[COMP_CWORD]}
  COMPREPLY=()
  local line
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ -z "$cur" || "$line" == "$cur"* ]]; then
      COMPREPLY+=("$line")
    fi
  done < <(printf '%s\\n' "\${COMP_WORDS[@]}" | command ${bin} --no-json completion candidates --shell bash --cword "$COMP_CWORD" 2>/dev/null)
}
complete -F _${bin}_completion -o default ${bin}
`;
}

export function zshCompletionBody(bin: string): string {
  return `_${bin}() {
  local -a lines
  lines=()
  local line
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    lines+=("$line")
  done < <(printf '%s\\n' "\${words[@]}" | command ${bin} --no-json completion candidates --shell zsh --cword "$CURRENT" 2>/dev/null)
  compadd -a lines
}
compdef _${bin} ${bin}
`;
}

export function fishCompletionBody(bin: string): string {
  return `function __fish_${bin}_completion_words
  set -l tok (commandline -opc)
  printf '%s\\n' $tok | command ${bin} --no-json completion candidates --shell fish --cword (math (count $tok) - 1) 2>/dev/null
end
complete -c ${bin} -f -a '(__fish_${bin}_completion_words)'
`;
}

export function powershellCompletionBody(bin: string): string {
  return `Register-ArgumentCompleter -Native -CommandName ${bin} -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $before = $commandAst.ToString().Substring(0, $cursorPosition)
  $parts = @($before -split '\\s+' | Where-Object { $_ -ne '' })
  $cword = [Math]::Max(0, $parts.Count - 1)
  $words = ($parts | ForEach-Object { $_ }) -join [Environment]::NewLine
  $out = $words | & ${bin} --no-json completion candidates --shell powershell --cword $cword 2>$null
  if (-not $out) { return }
  $out -split '\\r?\\n' | Where-Object { $_ -and ($_ -like ($wordToComplete + '*')) } | ForEach-Object {
    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
  }
}
`;
}
