#!/usr/bin/env bash
# Run the Linux UI smoke list with one private desktop environment per script.
set -euo pipefail

if [[ ${1:-} == --run-one ]]; then
  log_dir=$2
  script=$3
  name=${script##*/}
  log="$log_dir/$name.log"
  started=$SECONDS
  status=0
  dbus-run-session -- bash -ec '
    profile=$(mktemp -d "${RUNNER_TEMP:-/tmp}/umeko-ui.XXXXXX")
    trap '\''rm -rf -- "$profile"'\'' EXIT
    export XDG_DATA_HOME="$profile/data" XDG_CONFIG_HOME="$profile/config"
    export XDG_CACHE_HOME="$profile/cache" XDG_RUNTIME_DIR="$profile/run"
    export UMEKO_DATA_DIR="$profile/profile"
    export PI_CODING_AGENT_DIR="$profile/agent"
    mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR" "$UMEKO_DATA_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
    printf "ci-ephemeral-password" | gnome-keyring-daemon --unlock --components=secrets
    .venv/bin/python "$1"
  ' _ "$script" >"$log" 2>&1 || status=$?
  elapsed=$((SECONDS - started))
  printf '%s\t%s\t%s\n' "$script" "$elapsed" "$status" >"$log_dir/$name.result"
  # One output lock keeps completed-script groups readable while xargs schedules.
  {
    flock 9
    echo "::group::UI smoke: $script (exit=$status, ${elapsed}s)"
    if (( status == 0 )); then tail -n 10 "$log"; else cat "$log"; fi
    echo '::endgroup::'
    if (( status != 0 )); then echo "::error file=$script::UI smoke failed: $script (exit $status)"; fi
  } 9>"$log_dir/.output.lock"
  # Do not return 255: xargs must finish the remaining scripts after a failure.
  if (( status != 0 )); then exit 1; fi
  exit 0
fi

jobs=${CI_UI_SMOKE_JOBS:-$(nproc)}
if [[ ${1:-} == --jobs ]]; then jobs=$2; shift 2; fi
if [[ $# != 0 || ! $jobs =~ ^[1-9][0-9]*$ ]]; then
  echo 'Usage: bash scripts/ci-ui-smokes.bash [--jobs N]' >&2
  exit 2
fi
# Slowest scripts first, using timings from CI run 41779809091.
smokes=(
  tests/model_popup_ui_smoke.py
  tests/pi_capabilities_ui_smoke.py
  tests/global_agents_ui_smoke.py
  tests/desktop_plugins_ui_smoke.py
  tests/pi_management_ui_smoke.py
  tests/subagent_collection_ui_smoke.py
  tests/thinking_stream_ui_smoke.py
  tests/skill_manager_host_ui_smoke.py
  tests/video_ui_smoke.py
  tests/desktop_pet_ui_smoke.py
  tests/subagent_pane_ui_smoke.py
  tests/multimodal_ui_smoke.py
  tests/auxiliary_vision_ui_smoke.py
  tests/appearance_ui_smoke.py
  tests/characters_ui_smoke.py
  tests/sidebar_animation_ui_smoke.py
  tests/extension_details_ui_smoke.py
  tests/provider_popup_ui_smoke.py
  tests/model_reasoning_ui_smoke.py
  tests/reasoning_auto_ui_smoke.py
  tests/reasoning_detection_ui_smoke.py
  tests/change_review_ui_smoke.py
  tests/motion_ui_smoke.py
  tests/codearts_plugin_ui_smoke.py
  tests/subagent_reaction_ui_smoke.py
  tests/viewport_cache_ui_smoke.py
  tests/subagent_queue_ui_smoke.py
  tests/preview_resize_ui_smoke.py
  tests/api_proxy_layout_ui_smoke.py
  tests/large_chat_ui_smoke.py
  tests/provider_error_ui_smoke.py
  tests/desktop_settings_ui_smoke.py
  tests/login_startup_ui_smoke.py
  tests/login_startup_launch_smoke.py
  tests/sidebar_highlight_ui_smoke.py
  tests/chat_loading_ui_smoke.py
  tests/scroll_paging_ui_smoke.py
  tests/task_state_ui_smoke.py
  tests/steering_status_ui_smoke.py
  tests/conversation_search_ui_smoke.py
  tests/sidebar_menu_position_ui_smoke.py
  tests/pi_manager_initial_tools_ui_smoke.py
  tests/slash_commands_ui_smoke.py
  tests/large_markdown_ui_smoke.py
  tests/history_window_ui_smoke.py
  tests/request_details_ui_smoke.py
  tests/skill_manager_ui_smoke.py
  tests/provider_login_cancel_ui_smoke.py
  tests/pid_thread_ui_smoke.py
  tests/input_method_ui_smoke.py
)

mkdir -p build
log_dir=$(mktemp -d "$PWD/build/ui-smokes.XXXXXX")
started=$SECONDS
echo "Running ${#smokes[@]} UI smokes across $jobs workers"
status=0
printf '%s\0' "${smokes[@]}" | xargs -0 -n 1 -P "$jobs" bash "$0" --run-one "$log_dir" || status=$?
echo "ui_smokes completed in $((SECONDS - started)) seconds (exit=$status)"
exit "$status"
