# ═══════════════════════════════════════════════════════════════
#  terminal-setup · git and GitHub shortcuts  (loaded by zsh/zshrc)
#  ghelp prints them all in the terminal · Ctrl+a ? / keys git: the guide
#  The gh ones (gpr, gprc, gprv, gprs, gprm, gci) need https://cli.github.com
#  and `gh auth login` once.
#  Every name here is listed in the guide (tmux/guide.zsh, Terminal tab · Git & GitHub):
#  add a new one there too, so ghelp shows it.
# ═══════════════════════════════════════════════════════════════

# a name defined here wins over an alias with that name set earlier in ~/.zshrc
unalias gst glog gd gds ga gaa gc gcm gca gcb gsw gl gp gpf gco gundo gclean \
        gpr gprc gprv gprs gprm gci ghelp 2>/dev/null

# ─────────────── Diffs through delta ───────────────
# Only when git has no pager of its own (core.pager / GIT_PAGER): yours always wins.
# Set through the environment, so ~/.gitconfig is never touched.
if (( $+commands[delta] )) && [[ -z $GIT_PAGER ]] && ! git config --get core.pager &>/dev/null; then
  typeset -i _n=${GIT_CONFIG_COUNT:-0}
  export GIT_CONFIG_KEY_$_n=core.pager                  GIT_CONFIG_VALUE_$_n=delta
  export GIT_CONFIG_KEY_$((_n+1))=interactive.diffFilter GIT_CONFIG_VALUE_$((_n+1))='delta --color-only'
  export GIT_CONFIG_KEY_$((_n+2))=delta.navigate         GIT_CONFIG_VALUE_$((_n+2))=true
  export GIT_CONFIG_COUNT=$((_n+3))
  unset _n
fi

# ─────────────── Everyday ───────────────

alias gst='git status -sb'
alias glog="git log --graph --all --pretty=format:'%C(yellow)%h%C(reset)%C(auto)%d%C(reset) %s %C(dim)· %cr · %an%C(reset)'"
alias gd='git diff'
alias gds='git diff --staged'
alias ga='git add'
alias gaa='git add -A'
alias gc='git commit -v'                     # -v: the diff is in the editor, below the message
alias gcm='git commit -m'
alias gca='git commit --amend --no-edit'
alias gcb='git switch -c'
alias gsw='git switch'
alias gl='git pull'
alias gpf='git push --force-with-lease'      # refuses when someone else pushed in between

_g_repo() { git rev-parse --git-dir &>/dev/null || { print -u2 "not inside a git repository"; return 1 } }
_g_gh()   { (( $+commands[gh] )) || { print -u2 "needs gh: https://cli.github.com (then: gh auth login)"; return 1 } }

# push · the first push of a branch also sets its upstream (origin, or the only remote)
gp() {
  _g_repo || return
  local branch=$(git branch --show-current)
  if [[ -n $branch ]] && ! git rev-parse --abbrev-ref '@{u}' &>/dev/null; then
    local -a remotes=(${(f)"$(git remote)"})
    local remote=origin
    (( ${remotes[(Ie)origin]} )) || remote=$remotes[1]
    [[ -z $remote ]] && { print -u2 "no remote: git remote add origin <url>"; return 1 }
    git push --set-upstream "$remote" "$branch" "$@"
  else
    git push "$@"
  fi
}

# switch branch · no name: pick one with fzf (local and remote, newest first, with its log)
gco() {
  (( $# )) && { git checkout "$@"; return }
  _g_repo || return
  (( $+commands[fzf] )) || { git branch -a; print -u2 "gco <branch> (fzf is missing for the picker)"; return 1 }
  local line
  # kind <TAB> ref <TAB> when <TAB> subject · remote branches that exist locally are left out
  line=$(git for-each-ref --sort=-committerdate \
           --format='%(symref)%09%(refname)%09%(refname:short)%09%(committerdate:relative)%09%(subject)' \
           refs/heads refs/remotes \
         | awk -F'\t' '
             $1 != "" { next }                                   # origin/HEAD
             { n++; full[n] = $2; ref[n] = $3; when[n] = $4; subj[n] = $5
               if ($2 ~ /^refs\/heads\//) local_[$3] = 1 }
             END {
               for (i = 1; i <= n; i++) {
                 if (full[i] ~ /^refs\/heads\//) kind = "L"
                 else { b = ref[i]; sub(/^[^\/]*\//, "", b); if (b in local_) continue; kind = "R" }
                 printf "%s\t%s\t\033[2m%-14s\033[0m %s\n", kind, ref[i], when[i], subj[i]
               }
             }' \
         | fzf --ansi --delimiter='\t' --with-nth=2,3 --height=60% --layout=reverse \
               --border=rounded --border-label=' branches ' --prompt='branch ❯ ' --pointer='▶' \
               --header='enter switches · remote ones get a local branch that tracks them · esc cancels' \
               --preview='git log --graph --color=always --format="%C(yellow)%h%C(reset) %s %C(dim)· %cr · %an" -n 40 {2}' \
               --preview-window=right,55%,border-left) || return 0
  local kind=${line%%$'\t'*} ref=${${line#*$'\t'}%%$'\t'*}
  if [[ $kind == R ]]; then
    git switch --track "$ref"
  else
    git switch "$ref"
  fi
}

# take back the last commit · its changes stay staged
gundo() {
  _g_repo || return
  git rev-parse --verify -q 'HEAD~1' >/dev/null || { print -u2 "nothing to undo: this is the first commit"; return 1 }
  print -r -- "undoing: $(git log -1 --format='%h %s')"
  git reset --soft 'HEAD~1'
}

# delete the local branches already merged, or whose remote branch is gone (a merged PR) · asks first
gclean() {
  _g_repo || return
  git fetch --prune --quiet 2>/dev/null
  local current=$(git branch --show-current) main
  main=$(git symbolic-ref --short -q refs/remotes/origin/HEAD 2>/dev/null); main=${main#*/}
  if [[ -z $main ]]; then
    for main in main master ''; do git rev-parse --verify -q "refs/heads/$main" >/dev/null && break; done
  fi
  local -a merged gone
  [[ -n $main ]] && merged=(${(f)"$(git branch --merged "$main" --format='%(refname:short)')"})
  gone=(${(f)"$(git for-each-ref --format='%(refname:short)%09%(upstream:track)' refs/heads | awk -F'\t' '$2 == "[gone]" { print $1 }')"})
  merged=(${merged:#($current|$main)}) gone=(${gone:#($current|$main)})
  gone=(${gone:|merged})                      # each branch once
  if (( ! $#merged && ! $#gone )); then print -r -- "nothing to clean"; return 0; fi
  (( $#merged )) && print -r -- "merged into ${main}:" && print -rl -- "  "$^merged
  (( $#gone ))   && print -r -- "remote branch gone (unmerged changes are lost):" && print -rl -- "  "$^gone
  read -q "?delete them? (y/N) " || { print; return 1 }
  print
  (( $#merged )) && git branch -d -- $merged
  (( $#gone ))   && git branch -D -- $gone
}

# ─────────────── GitHub (gh) ───────────────

# pull requests · enter checks one out, ctrl+o opens it in the browser · gpr 123: check out #123
gpr() {
  _g_gh || return
  (( $# )) && { gh pr checkout "$@"; return }
  _g_repo || return
  local list
  list=$(gh pr list --limit 100 --json number,title,headRefName,author,isDraft \
           --template '{{range .}}{{.number}}{{"\t"}}#{{.number}}  {{.title}}{{if .isDraft}}  (draft){{end}}  {{"\033[2m"}}{{.headRefName}} · {{.author.login}}{{"\033[0m"}}{{"\n"}}{{end}}') || return
  [[ -z $list ]] && { print -r -- "no open pull requests"; return 0 }
  (( $+commands[fzf] )) || { print -r -- "${list#*$'\t'}"; return 0 }
  local -a out
  out=("${(@f)$(print -r -- "$list" | fzf --ansi --delimiter='\t' --with-nth=2 --height=70% --layout=reverse \
          --border=rounded --border-label=' pull requests ' --prompt='PR ❯ ' --pointer='▶' \
          --header='enter checks it out · ctrl+o opens it in the browser · esc cancels' \
          --preview='GH_FORCE_TTY=$FZF_PREVIEW_COLUMNS gh pr view {1}' --preview-window=right,55%,border-left \
          --expect=ctrl-o)}") || return 0
  local key=$out[1] num=${out[2]%%$'\t'*}
  [[ -z $num ]] && return 0
  if [[ $key == ctrl-o ]]; then gh pr view "$num" --web; else gh pr checkout "$num"; fi
}

# push this branch and create its PR, title and text from the commits · gprc --draft · gprc --web
gprc() { _g_gh && gp && gh pr create --fill "$@" }

# this branch's PR in the browser (the repo when there is no PR)
gprv() { _g_gh || return; gh pr view --web "$@" 2>/dev/null || gh repo view --web }

alias gprs='gh pr status'                    # your PRs: this branch, created by you, asking for your review
alias gprm='gh pr merge'                     # asks how (merge, squash, rebase)

# CI of this branch · the PR's checks live until they finish · gci watch: follow a run
gci() {
  _g_gh || return
  [[ $1 == watch ]] && { shift; gh run watch "$@"; return }
  if gh pr view --json number &>/dev/null; then
    gh pr checks --watch "$@"
  else
    print -r -- "no PR for this branch: its latest runs (gci watch follows one)"
    gh run list --branch "$(git branch --show-current)" --limit 10
  fi
}

# ─────────────── Help ───────────────

# every shortcut above, in the terminal · ghelp pr: only the ones about PRs
ghelp() { $TERMINAL_SETUP/tmux/guide.zsh -p git "$@" }

# completion: like the git command they stand for
if (( $+functions[compdef] )); then
  compdef _git gco=git-checkout gp=git-push gundo=git-reset
  (( $+functions[_gh] )) && compdef _gh gpr gprc gprv gci
fi
