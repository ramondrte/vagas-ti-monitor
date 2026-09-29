# Monitor de vagas de TI — GitHub Actions

Pesquisa de estágios e vagas júnior/entrada em Governança de TI, Infraestrutura, NOC, ITSM, Suporte, Operações, Cloud e Segurança/GRC compatível com Sistemas de Informação, 3º semestre. Presencial/híbrido: Belo Horizonte, Contagem e Nova Lima/MG; remoto: Brasil, inclusive internacional apenas com autorização explícita para trabalhar do Brasil.

## Execução independente do computador

O workflow `.github/workflows/monitor-vagas.yml` roda em `ubuntu-latest`, hospedado pelo GitHub. Não depende de Mac, aplicativo, chat, sessão local, serviço de IA ou chave de API paga. Python 3.12 e biblioteca padrão fazem a coleta, análise por regras, SQLite, persistência e envio.

O cron está definido para **minuto 17 de cada hora**, em UTC (também minuto 17 no horário de Brasília). **A execução automática permanece bloqueada enquanto a variável de repositório `MONITOR_ENABLED` não for `true`.** A execução manual funciona sem essa variável.

GitHub pode atrasar ou deixar de executar schedules sob carga; não é um serviço com garantia de horário exato. A próxima janela, após ativação, é o próximo minuto 17. Em repositórios públicos, workflows agendados podem ser desativados após 60 dias sem atividade; confira periodicamente a aba Actions. Os commits de estado ficam separados do código; não dependa deles como garantia contra desativação.

Referências: [eventos e agendamento](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [preços e gratuidade](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Gratuito

O repositório é público e usa runner padrão, sem runners maiores, self-hosted, cache, artifacts, banco externo, cartão ou API paga. A documentação do GitHub informa gratuidade de runners padrão em repositórios públicos. O workflow bloqueia execução se este repositório virar privado, para evitar consumir cota faturável. Não ative serviços de terceiros para esta rotina.

## Secrets — configurar antes do teste de e-mail

No repositório, abra **Settings → Secrets and variables → Actions → Secrets → New repository secret**.

| Nome exato | Valor a inserir somente no formulário seguro do GitHub |
|---|---|
| `SMTP_USER` | Endereço da conta Gmail que enviará e receberá os alertas |
| `SMTP_PASSWORD` | Senha de app criada nessa Conta Google |

Somente esses **dois Secrets** são necessários. O token temporário `GITHUB_TOKEN` é fornecido automaticamente pelo GitHub e serve para persistir o histórico; não crie PAT. O workflow concede `contents: write` somente ao job necessário. SMTP usa `smtp.gmail.com:465` com TLS e validação de certificado; remetente e destinatário são a conta em SMTP_USER. Não há OAuth/Gmail API porque SMTP com senha de app atende à arquitetura sem serviços extras.

Gere a senha de app em [Conta Google](https://myaccount.google.com/apppasswords), com verificação em duas etapas ativada. Não use senha normal do Gmail, não envie a senha no chat, não crie `.env` no repositório e não coloque valores em comandos, README ou commits. [Orientação oficial do Google](https://support.google.com/mail/answer/185833?hl=pt-BR).

O runner ignora qualquer `.env` e recebe os valores apenas como variáveis de ambiente do passo de execução. Nenhum valor é impresso, incluído no snapshot ou passado como argumento de linha de comando. Não habilite debug SMTP ou dumps de ambiente. Os testes rodam em outro passo, sem Secrets.

## Primeira execução e ativação

1. O código e workflow precisam estar na branch padrão `main`.
2. Abra **Actions → Monitor de vagas TI → Run workflow**.
3. Primeiro rode `mode=dry-run`, `bootstrap=true`. Isso importa o histórico já existente em `seed_history.json` para a branch `monitor-state`, coleta e analisa vagas, sem enviar e-mail. Após a primeira criação, bootstrap pode ficar false; se a branch existir ele nunca substitui o histórico pela seed.
4. Crie os dois Secrets acima. Avise no chat que foram configurados, sem compartilhar valores.
5. Rode `mode=test-email`, `bootstrap=false`. A rotina faz busca real e manda **um teste explícito**. O teste tem ID persistente e não se repete se já foi aceito pelo SMTP. Aceite SMTP não garante chegada à caixa principal; confira também Spam.
6. Rode `mode=live`, `bootstrap=false` para testar o resumo real, caso existam vagas novas. Uma segunda execução não pode reenviar as mesmas versões.
7. Verifique status, sumário, logs, `deliveries` e `sent` na branch `monitor-state`. Só depois crie a **variável**, não Secret, `MONITOR_ENABLED=true` em **Settings → Secrets and variables → Actions → Variables → New repository variable**. Assim o cron é liberado. O agente só fará esta ativação após o teste solicitado.

O envio de teste é uma exceção única, autorizada, à regra de novidades. Execuções live sem novidades não mandam e-mail. `test-email` testa SMTP; `dry-run` nunca usa o transporte; não confunda esses resultados.

## Persistência confiável no runner temporário

A fonte permanente de verdade é **`monitor-state/state.json`** em branch separada, criada sem parentesco com o código. A cada execução:

1. Lê a referência e o blob da branch pela API GitHub e restaura as tabelas em SQLite no runner temporário.
2. Pesquisa, analisa e atualiza a base.
3. Publica checkpoint antes de enviar. Imediatamente antes do SMTP, persiste `deliveries.status=sending` na branch.
4. Depois de aceite SMTP, salva `sent` e `deliveries.status=accepted` em novo commit.
5. Finaliza com log da execução e novo checkpoint. Ao encerrar o runner, o SQLite local pode desaparecer; a branch preserva a informação.

Não depende de Cache (pode expirar/ser removido) nem de Artifacts (retenção limitada). Snapshot JSON usa allowlist de tabelas, sem arquivos de ambiente, credenciais ou HTML integral. Mantém os registros, motivos, identificadores, versões e logs; descrições são novamente coletadas nas páginas públicas. A seed preserva os dados anteriores: 4 candidatos, 3 vagas analisadas, 7 aliases, 13 execuções e nenhum envio. Não apaga nem reinicializa `sent`.

`concurrency` serializa execuções manuais e agendadas, com `cancel-in-progress: false`. Atualizações da branch usam fast-forward, sem force push; conflitos falham sem sobrescrever o estado. Branch existente sem snapshot, schema inválido ou ausência da branch numa rodada normal causam erro, nunca reset silencioso. Proteções de branch não podem impedir o GITHUB_TOKEN de atualizar `monitor-state`; se impedirem, o fluxo falha antes do SMTP.

Se o runner cair após enviar mas antes de confirmar a persistência, a branch já contém `sending`. A próxima execução bloqueia o envio, em vez de repetir cegamente. Confira Enviados e reconcilie `deliveries`/`sent` com evidência antes de liberar. SMTP não oferece transação atômica com Git; não é possível prometer exactly-once. Esse desenho prioriza evitar duplicatas, podendo exigir intervenção após falha incerta.

Não apague a branch `monitor-state` nem rode bootstrap após perda de histórico sem restaurar o último commit. O JSON é versionado; é possível recuperar revisões antigas. O sistema bloqueia snapshot acima de 20 MB para manutenção, sem apagar histórico de envios. Todos os dados versionados são públicos: vagas e registros técnicos, sem destinatário ou credenciais.

## Componentes preservados e migração

- `monitor.py`: coleta, validação, SQLite, deduplicação, formatação e SMTP originais, com checkpoint remoto e configuração portátil.
- `config.json` e `BUSCAS.md`: cargos, palavras e **385 consultas originais** preservados. Dados de destinatário foram retirados do arquivo público.
- `analyzer.py`: substitui a análise que dependia deste chat por regras determinísticas sobre seções de atividades, requisitos, localidade e dados JobPosting. Sem modelo pago.
- `sources.py`: consultas RSS rotativas e leitura de listagens oficiais, com fila persistente de anúncios.
- `state_store.py`: restauração e commits de estado via GitHub API, com token temporário.
- `cloud_run.py`: ponto de entrada independente para o workflow.
- `test_monitor.py` e `test_cloud.py`: testes de filtros, deduplicação, migração, falhas e envio simulado.

A análise automática é conservadora e **não equivale à interpretação humana/LLM anterior**. Casos sem estrutura, requisitos ambíguos ou candidatura não confirmada ficam `pending` e não são enviados. Há risco de perder oportunidades com descrição incompleta; não há alegação de cobertura total. As decisões e seus motivos ficam auditáveis no histórico.

## Fontes e cobertura

Consultas preservadas para LinkedIn Jobs, Indeed, Gupy, Greenhouse, Lever, Workday, InHire, Abler, Vagas.com, CIEE, Nube, Eureca, Bettha, páginas/programas oficiais e empresas-alvo. Pesquisa pública por RSS não garante resultados de todas essas fontes. Não há APIs autenticadas nem scraping de páginas protegidas.

Listagens diretas configuradas inicialmente: Santa Casa BH, Cadastra, Wyntech e Teknisa na Gupy. `boards` permite acrescentar páginas oficiais. O coletor lê links públicos e dados estruturados; não contorna CAPTCHA, Cloudflare ou login. Sem JSON-LD JobPosting ou confirmação de candidatura, o anúncio fica pendente. Links de agregadores não são aceitos como oficiais só pelo título; pode ser necessário adicionar o anúncio oficial a uma listagem ou fonte.

Cada rodada usa 16 consultas em rotação e até 40 anúncios, evitando sobrecarga. O catálogo completo leva cerca de 25 rodadas. Fila ordenada pela última coleta assegura reavaliação contínua. Governança tem prioridade de descoberta no catálogo; a área principal é classificada pelo foco das atividades, e a prioridade de envio preserva estágio antes de entrada e Governança > Infraestrutura > NOC > ITSM > Suporte > Operações.

## Filtros e formato

Não basta mencionar TI/Sistemas. A análise procura atividades compatíveis em seções próprias; não usa o texto institucional para transformar governança corporativa em TI. Programação complementar/desejável não exclui; programação predominante exclui. Rejeita senioridade elevada, graduação concluída obrigatória, experiência incompatível, semestre fora do intervalo e prazo encerrado. Um requisito desejável não é automaticamente obrigatório.

Campos não informados ficam “Não informado / precisa confirmar”. Sem comprovação de localidade, nível, curso de estágio ou candidatura, fica pendente. Requisitos de previsão de formatura são destacados; a previsão pessoal do candidato não foi fornecida e pode precisar de confirmação. Vagas de entrada sem exigência de diploma concluído são aceitas se as demais regras forem atendidas.

E-mail único: empresa, cargo, local, modalidade, área, salário, benefícios, jornada, curso, semestre, formatura, atividades, requisitos, desejáveis, prazo, publicação, link oficial, fonte, data encontrada e explicação de compatibilidade. Sem nota numérica ou ranking de empresas. Alterações significativas reaparecem como “Vaga atualizada”. Assunto preservado: “🚨 Novas vagas de estágio em TI — X vagas encontradas”.

## Logs e manutenção

Logs de console e sumário ficam em Actions, conforme retenção do GitHub. A tabela `runs` em `state.json` mantém histórico permanente de status e resultados; `candidates.error` e `jobs.reason` explicam falhas e decisões. `sent` guarda versões enviadas; `deliveries` guarda tentativa e aceite SMTP. Um envio incerto exige intervenção, não retentativa automática.

Para alterar perfil: edite `cities`, `semester`, `area_order`, `terms`, `keywords` e `queries` em config.json. `official_domains` valida hosts oficiais; adicionar domínio de agregador aqui não é correto. Novas listagens entram em `boards`; novas consultas em `queries`. Estruturas específicas de ATS podem exigir adaptação do parser e testes. O limite conservador de experiência e padrões ficam em analyzer.py/monitor.py.

Para pausar: mude `MONITOR_ENABLED` para `false`; execução manual continua disponível. Para desativar tudo: Actions → workflow → Disable workflow. Preserve monitor-state. O agendamento antigo do aplicativo permanece pausado e não é necessário.

## Testes

```sh
python3 -m unittest discover -p 'test_*.py'
# Smoke local sem e-mail; não usa nem altera a branch remota:
python3 cloud_run.py --local-test --mode dry-run --queries 4 --pages 8
```

O teste local deve usar MONITOR_ROOT apontando para pasta temporária com config.json para não alterar a base local original. Testes automatizados não exigem Secrets. Validação adicional do YAML: actionlint .github/workflows/monitor-vagas.yml.

Na migração, os testes locais passaram, actionlint aprovou o workflow e uma busca real encontrou 40 links em quatro listagens oficiais, com oito anúncios analisados. **Isso não substitui o teste no runner real e o aceite SMTP com Secrets.** O cron só deve ser liberado após as verificações da primeira execução descritas acima.
