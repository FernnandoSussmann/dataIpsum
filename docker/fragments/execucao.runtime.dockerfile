# Trilha D (DD-01, execucao): DD-01 §D.10.
#
# Desliga a telemetria de uso do Ray (evita chamada de rede não solicitada, mesmo em
# imagens sem EXTRAS=ray: o ENV não tem custo e vale para o worker Ray, que roda a
# mesma imagem trocando só o ENTRYPOINT, sem EXTRAS=ray mudar nada aqui).
ENV RAY_USAGE_STATS_ENABLED=0

# DATAIPSUM_CPU_MAX/DATAIPSUM_MEM_MAX (DD-01 §D.3.4, DD-00 §3.8) são lidos por env em
# runtime; a imagem não fixa valores (nenhum ENV para eles aqui, de propósito).
