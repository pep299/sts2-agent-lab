# GitHub Interaction limits の維持

## 背景・目的

このリポジトリはPublicだが、現時点では権限のない第三者によるIssue・PRの作成やコメントを受け付けない。

Issue・PRの新規作成は別途制限しているが、既存のIssue・PRへのコメントも防ぐため、GitHubのInteraction limitsを `collaborators_only` に設定している。

この設定には有効期限があり、失効すると外部から投稿できるようになるため、継続的な更新が必要となる。

更新頻度が低く、自動化のための認証・定期実行の管理を増やすほどではないため、自動更新は設けず、必要に応じてAIエージェントに更新を依頼する。

## 更新手順

実行時には[GitHub公式ドキュメント](https://docs.github.com/en/rest/interactions/repos)を確認し、本Runbookの背景・目的・更新手順が前提としている仕様に変更がないか確認する。変更があれば適宜対応し、必要に応じて本Runbookも修正する。

以下は**2026-10-10時点**のGitHub API仕様に基づく操作例。

**更新**

```bash
gh api -X PUT repos/pep299/sts2-agent-lab/interaction-limits \
  -f limit=collaborators_only \
  -f expiry=six_months
```

**確認**

```bash
gh api repos/pep299/sts2-agent-lab/interaction-limits
```

更新後は、意図した制限が有効であり、有効期限が更新されていることを確認する。失敗した場合は完了とみなさない。
