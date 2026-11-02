#!/bin/sh
# Git 凭据问答：用户名由 GIT_MIRROR_USERNAME 指定，密码从 $TOKEN 读。
# 令牌只在环境变量里，不写入任何文件或远程 URL。
case "$1" in
  *Username*) printf '%s\n' "${GIT_MIRROR_USERNAME:-oauth2}" ;;
  *Password*) printf '%s\n' "$TOKEN" ;;
  *) printf '\n' ;;
esac
