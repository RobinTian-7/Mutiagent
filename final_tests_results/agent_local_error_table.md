# Agent Local Error Table

`Frame = -1` is the post-initialization state. `LocalRMSE` compares the agent's `merged_counts` with the scoring-only truth for its `KnownSources`; `GlobalRMSE` compares the same answer with the full global answer.

| Topology | Agents | Seed | MergeMode | InitMode | Frame | Phase | Agent | ActiveReceiver | Received | KnownSources | KnownSourceCount | KnownItemCount | Coverage | LocalRMSE | GlobalRMSE | LocalL1 | GlobalL1 | LocalExact | GlobalExact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.196152 | 133.292911 | 0.021600 | 0.751400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.324555 | 134.342845 | 0.028800 | 0.754800 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.830952 | 133.917885 | 0.027200 | 0.756400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 4.795832 | 133.322916 | 0.016800 | 0.753800 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.196152 | 133.292911 | 0.021600 | 0.751400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 2500 | 0.500000 | 8.426150 | 94.873600 | 0.026000 | 0.506600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.830952 | 133.917885 | 0.027200 | 0.756400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 4.795832 | 133.322916 | 0.016800 | 0.753800 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.196152 | 133.292911 | 0.021600 | 0.751400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 8.426150 | 94.873600 | 0.026000 | 0.506600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 3750 | 0.750000 | 18.920888 | 57.706152 | 0.061333 | 0.269600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 4.795832 | 133.322916 | 0.016800 | 0.753800 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.196152 | 133.292911 | 0.021600 | 0.751400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 8.426150 | 94.873600 | 0.026000 | 0.506600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 3750 | 0.750000 | 18.920888 | 57.706152 | 0.061333 | 0.269600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 28.035692 | 28.035692 | 0.089600 | 0.089600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.316625 | 153.231850 | 0.014400 | 0.876800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 3.316625 | 152.996732 | 0.011200 | 0.876400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 1.414214 | 153.293835 | 0.003200 | 0.875400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.464102 | 152.692501 | 0.016000 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 4.472136 | 153.391656 | 0.025600 | 0.876600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 3.316625 | 152.996732 | 0.011200 | 0.876400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 1.414214 | 153.293835 | 0.003200 | 0.875400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.464102 | 152.692501 | 0.016000 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 4.472136 | 153.391656 | 0.025600 | 0.876600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 1.414214 | 153.293835 | 0.003200 | 0.875400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.464102 | 152.692501 | 0.016000 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 4.472136 | 153.391656 | 0.025600 | 0.876600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 56.797887 | 135.447407 | 0.513600 | 0.756000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.464102 | 152.692501 | 0.016000 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 4.472136 | 153.391656 | 0.025600 | 0.876600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 56.797887 | 135.447407 | 0.513600 | 0.756000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 17.349352 | 76.915538 | 0.077120 | 0.395200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 4.472136 | 153.391656 | 0.025600 | 0.876600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 56.797887 | 135.447407 | 0.513600 | 0.756000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 17.349352 | 76.915538 | 0.077120 | 0.395200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 24.556058 | 58.574739 | 0.121867 | 0.278200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.828427 | 153.561063 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 56.797887 | 135.447407 | 0.513600 | 0.756000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 17.349352 | 76.915538 | 0.077120 | 0.395200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 24.556058 | 58.574739 | 0.121867 | 0.278200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 6 | True | 1 | [0, 1, 2, 3, 4, 5, 6] | 7 | 4375 | 0.875000 | 134.309344 | 154.938698 | 0.868800 | 0.885200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.242641 | 133.461605 | 0.012800 | 0.752800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 15.297059 | 118.021185 | 0.082133 | 0.655000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 56.797887 | 135.447407 | 0.513600 | 0.756000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 17.349352 | 76.915538 | 0.077120 | 0.395200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 24.556058 | 58.574739 | 0.121867 | 0.278200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 4375 | 0.875000 | 134.309344 | 154.938698 | 0.868800 | 0.885200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 143.701079 | 143.701079 | 0.797200 | 0.797200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 313 | 0.062600 | 1.414214 | 162.791277 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 0.000000 | 162.576136 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 1.732051 | 163.058272 | 0.009585 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.732051 | 162.886464 | 0.009585 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 0.000000 | 162.576136 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 1.732051 | 163.058272 | 0.009585 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.732051 | 162.886464 | 0.009585 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 1.732051 | 163.058272 | 0.009585 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.732051 | 162.886464 | 0.009585 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.732051 | 162.886464 | 0.009585 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 6 | True | 1 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.414214 | 162.981594 | 0.006390 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.414214 | 162.990797 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 8 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 9 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 10 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 11 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 3752 | 0.750400 | 105.285327 | 144.086779 | 0.740672 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 3752 | 0.750400 | 105.285327 | 144.086779 | 0.740672 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 12 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 4064 | 0.812800 | 32.588341 | 59.949979 | 0.163386 | 0.290400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 3752 | 0.750400 | 105.285327 | 144.086779 | 0.740672 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 4064 | 0.812800 | 32.588341 | 59.949979 | 0.163386 | 0.290400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 13 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 4376 | 0.875200 | 126.873953 | 146.809400 | 0.774452 | 0.800600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 3752 | 0.750400 | 105.285327 | 144.086779 | 0.740672 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 4064 | 0.812800 | 32.588341 | 59.949979 | 0.163386 | 0.290400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 4376 | 0.875200 | 126.873953 | 146.809400 | 0.774452 | 0.800600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 14 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 4688 | 0.937600 | 134.368895 | 144.086779 | 0.787756 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.000000 | 162.911019 | 0.003195 | 0.937600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 1.732051 | 153.078411 | 0.004792 | 0.875400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 939 | 0.187800 | 4.123106 | 143.317829 | 0.018104 | 0.815600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 37.973675 | 156.556699 | 0.602236 | 0.892000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 1565 | 0.313000 | 38.078866 | 145.893797 | 0.438339 | 0.824200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 1878 | 0.375600 | 62.265560 | 162.446914 | 0.831203 | 0.936600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2191 | 0.438200 | 64.853681 | 155.302930 | 0.746691 | 0.889000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 17.748239 | 94.376904 | 0.102636 | 0.497800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 2816 | 0.563200 | 82.304313 | 150.179892 | 0.723722 | 0.839200 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 3128 | 0.625600 | 40.087405 | 92.114060 | 0.198529 | 0.465000 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 3440 | 0.688000 | 36.249138 | 85.005882 | 0.200581 | 0.441600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 3752 | 0.750400 | 105.285327 | 144.086779 | 0.740672 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 4064 | 0.812800 | 32.588341 | 59.949979 | 0.163386 | 0.290400 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 4376 | 0.875200 | 126.873953 | 146.809400 | 0.774452 | 0.800600 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 4688 | 0.937600 | 134.368895 | 144.086779 | 0.787756 | 0.799800 | False | False |
| chain | 16 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 15 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 5000 | 1.000000 | 52.000000 | 52.000000 | 0.247600 | 0.247600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 157 | 0.031400 | 0.000000 | 167.693172 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 1.000000 | 167.618615 | 0.006369 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 0.000000 | 167.454471 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 1.000000 | 167.618615 | 0.006369 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 0.000000 | 167.454471 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 1.000000 | 167.618615 | 0.006369 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 0.000000 | 167.454471 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 0.000000 | 167.454471 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 0.000000 | 167.454471 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 0.000000 | 167.937488 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 6 | True | 1 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 8 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 9 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 10 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 11 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.000000 | 167.919624 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 12 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 11 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 13 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 12 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 14 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 13 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 15 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 14 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 16 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 15 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 17 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 16 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 18 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 17 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 19 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 1.000000 | 167.871975 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 18 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 20 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 1.000000 | 167.722986 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 19 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 21 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 20 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 22 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 21 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 23 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 22 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 24 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 23 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 25 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 24 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 26 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 25 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 26 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 27 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27] | 28 | 4376 | 0.875200 | 147.631297 | 168.098186 | 0.964122 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 2.000000 | 167.248318 | 0.012821 | 0.969200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 26 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 26 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 27 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27] | 28 | 4376 | 0.875200 | 147.631297 | 168.098186 | 0.964122 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 28 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28] | 29 | 4532 | 0.906400 | 43.954522 | 58.753723 | 0.218447 | 0.285600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 27 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 26 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 27 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27] | 28 | 4376 | 0.875200 | 147.631297 | 168.098186 | 0.964122 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 28 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28] | 29 | 4532 | 0.906400 | 43.954522 | 58.753723 | 0.218447 | 0.285600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 29 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29] | 30 | 4688 | 0.937600 | 149.479096 | 159.461594 | 0.894625 | 0.901200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 28 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 26 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 27 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27] | 28 | 4376 | 0.875200 | 147.631297 | 168.098186 | 0.964122 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 28 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28] | 29 | 4532 | 0.906400 | 43.954522 | 58.753723 | 0.218447 | 0.285600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 29 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29] | 30 | 4688 | 0.937600 | 149.479096 | 159.461594 | 0.894625 | 0.901200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 30 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30] | 31 | 4844 | 0.968800 | 53.730811 | 58.779248 | 0.267754 | 0.289800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 29 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.000000 | 162.871115 | 0.003185 | 0.937400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 471 | 0.094200 | 2.449490 | 158.237164 | 0.008493 | 0.906600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 2.828427 | 153.179633 | 0.012739 | 0.876000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 785 | 0.157000 | 29.732137 | 165.260401 | 0.687898 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 942 | 0.188400 | 6.082763 | 143.614066 | 0.028662 | 0.816600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 1099 | 0.219800 | 28.965497 | 154.977418 | 0.479527 | 0.885600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 6.557439 | 133.600150 | 0.032643 | 0.753000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 1412 | 0.282400 | 34.307434 | 147.278647 | 0.417139 | 0.835000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 1568 | 0.313600 | 55.668663 | 165.278553 | 0.843750 | 0.951000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 1724 | 0.344800 | 57.393379 | 160.218601 | 0.785383 | 0.917600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 11 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 1880 | 0.376000 | 64.233947 | 162.222070 | 0.817021 | 0.926000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 12 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] | 13 | 2036 | 0.407200 | 51.672043 | 144.409141 | 0.540275 | 0.812800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 13 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] | 14 | 2192 | 0.438400 | 77.768888 | 167.839209 | 0.928832 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 14 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 15 | 2348 | 0.469600 | 81.871851 | 166.868211 | 0.922913 | 0.963800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 87.903356 | 167.877932 | 0.936502 | 0.968200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 16 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16] | 17 | 2660 | 0.532000 | 70.349129 | 143.621029 | 0.632707 | 0.804600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 17 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] | 18 | 2816 | 0.563200 | 20.566964 | 89.392393 | 0.118253 | 0.468600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 18 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18] | 19 | 2972 | 0.594400 | 102.508536 | 167.320053 | 0.946164 | 0.968000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 19 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] | 20 | 3128 | 0.625600 | 107.990740 | 167.660371 | 0.950128 | 0.968800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 20 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] | 21 | 3284 | 0.656800 | 91.651514 | 145.003448 | 0.718636 | 0.808400 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 21 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21] | 22 | 3440 | 0.688000 | 117.868571 | 167.717024 | 0.954360 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 22 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22] | 23 | 3596 | 0.719200 | 115.472941 | 159.392597 | 0.863737 | 0.897200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 23 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] | 24 | 3752 | 0.750400 | 104.947606 | 143.840189 | 0.737207 | 0.798800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 24 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] | 25 | 3908 | 0.781600 | 132.796837 | 167.901757 | 0.959826 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 25 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25] | 26 | 4064 | 0.812800 | 114.804181 | 144.083309 | 0.758366 | 0.799600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 26 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26] | 27 | 4220 | 0.844000 | 142.446481 | 167.532086 | 0.960900 | 0.967000 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 27 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27] | 28 | 4376 | 0.875200 | 147.631297 | 168.098186 | 0.964122 | 0.968600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 28 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28] | 29 | 4532 | 0.906400 | 43.954522 | 58.753723 | 0.218447 | 0.285600 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 29 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29] | 30 | 4688 | 0.937600 | 149.479096 | 159.461594 | 0.894625 | 0.901200 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 30 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30] | 31 | 4844 | 0.968800 | 53.730811 | 58.779248 | 0.267754 | 0.289800 | False | False |
| chain | 32 | 1 | llm_full_merge | llm_local_solve | 30 | after_step | 31 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31] | 32 | 5000 | 1.000000 | 123.923363 | 123.923363 | 0.657800 | 0.657800 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 4.690416 | 133.341666 | 0.017600 | 0.752000 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 5.656854 | 133.902950 | 0.024000 | 0.752400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 7.141428 | 134.309344 | 0.029600 | 0.757400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.291503 | 133.251642 | 0.019200 | 0.753600 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 27.184554 | 27.184554 | 0.086200 | 0.086200 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 5.656854 | 133.902950 | 0.024000 | 0.752400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 7.141428 | 134.309344 | 0.029600 | 0.757400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.291503 | 133.251642 | 0.019200 | 0.753600 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.316625 | 153.205744 | 0.014400 | 0.876400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.359056 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.372097 | 0.019200 | 0.877000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.449490 | 153.515472 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 3.872983 | 152.564740 | 0.014400 | 0.876800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 37.815341 | 37.815341 | 0.152400 | 0.152400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.316625 | 153.205744 | 0.014400 | 0.876400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.359056 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.372097 | 0.019200 | 0.877000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.449490 | 153.515472 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 3.872983 | 152.564740 | 0.014400 | 0.876800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 313 | 0.062600 | 1.000000 | 162.769776 | 0.003195 | 0.937600 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 1.732051 | 162.659153 | 0.009585 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 2.000000 | 163.085867 | 0.012780 | 0.938200 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.414214 | 162.901811 | 0.006390 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.732051 | 163.003067 | 0.009585 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.000000 | 162.944776 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 15 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 5000 | 1.000000 | 53.581713 | 53.581713 | 0.245000 | 0.245000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 313 | 0.062600 | 1.000000 | 162.769776 | 0.003195 | 0.937600 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 1.732051 | 162.659153 | 0.009585 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 2.000000 | 163.085867 | 0.012780 | 0.938200 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.414214 | 162.901811 | 0.006390 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.732051 | 163.003067 | 0.009585 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 1.000000 | 162.944776 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.416132 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| star | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 157 | 0.031400 | 0.000000 | 167.693172 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 1.000000 | 167.851125 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 0.000000 | 167.597733 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 1.000000 | 167.827292 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 1.000000 | 167.499254 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 1.000000 | 167.842188 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 2.000000 | 168.041662 | 0.025641 | 0.969600 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.414214 | 167.857082 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.000000 | 167.806436 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 0.000000 | 167.660371 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 0.000000 | 167.666335 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.833251 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 0.000000 | 167.224400 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 0.000000 | 167.737891 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 31 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31] | 32 | 5000 | 1.000000 | 43.428102 | 43.428102 | 0.191200 | 0.191200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 157 | 0.031400 | 0.000000 | 167.693172 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 1.000000 | 167.851125 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 0.000000 | 167.597733 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 1.000000 | 167.827292 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 1.000000 | 167.499254 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 0.000000 | 167.591766 | 0.000000 | 0.968600 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 1.000000 | 167.842188 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 2.000000 | 168.041662 | 0.025641 | 0.969600 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.414214 | 167.857082 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.000000 | 167.806436 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 0.000000 | 167.660371 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 0.000000 | 167.666335 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.833251 | 0.012821 | 0.969200 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 0.000000 | 167.224400 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 0.000000 | 167.737891 | 0.000000 | 0.968800 | True | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| star | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.567764 | 133.247889 | 0.023200 | 0.751400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.000000 | 134.335401 | 0.025600 | 0.755200 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.744563 | 133.757243 | 0.026400 | 0.755000 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.196152 | 133.277905 | 0.020000 | 0.753800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.567764 | 133.247889 | 0.023200 | 0.751400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 2500 | 0.500000 | 13.190906 | 92.833184 | 0.060000 | 0.490400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.744563 | 133.757243 | 0.026400 | 0.755000 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 2500 | 0.500000 | 34.727511 | 115.646012 | 0.291200 | 0.645200 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.567764 | 133.247889 | 0.023200 | 0.751400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 13.190906 | 92.833184 | 0.060000 | 0.490400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.744563 | 133.757243 | 0.026400 | 0.755000 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 33.911650 | 33.911650 | 0.116800 | 0.116800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.605551 | 153.303620 | 0.017600 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.236068 | 153.355795 | 0.008000 | 0.875600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 4.000000 | 152.790707 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.398175 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.583853 | 0.011200 | 0.876400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 3.872983 | 152.577849 | 0.014400 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1250 | 0.250000 | 6.855655 | 134.078335 | 0.024800 | 0.755800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 1250 | 0.250000 | 4.582576 | 133.809566 | 0.013600 | 0.752600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 4.000000 | 152.790707 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 1250 | 0.250000 | 7.810250 | 134.026117 | 0.028000 | 0.756200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.583853 | 0.011200 | 0.876400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 1 | [6, 7] | 2 | 1250 | 0.250000 | 5.385165 | 133.352915 | 0.015200 | 0.753800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 6.855655 | 134.078335 | 0.024800 | 0.755800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 14.966630 | 92.509459 | 0.075200 | 0.492400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 4.000000 | 152.790707 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 1250 | 0.250000 | 7.810250 | 134.026117 | 0.028000 | 0.756200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.583853 | 0.011200 | 0.876400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 1 | [4, 5, 6, 7] | 4 | 2500 | 0.500000 | 17.720045 | 94.889409 | 0.076800 | 0.506000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 6.855655 | 134.078335 | 0.024800 | 0.755800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 14.966630 | 92.509459 | 0.075200 | 0.492400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 4.000000 | 152.790707 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [4, 5] | 2 | 1250 | 0.250000 | 7.810250 | 134.026117 | 0.028000 | 0.756200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.583853 | 0.011200 | 0.876400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 36.755952 | 36.755952 | 0.154200 | 0.154200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 313 | 0.062600 | 1.000000 | 162.745200 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 2.000000 | 162.674522 | 0.012780 | 0.938200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 313 | 0.062600 | 1.414214 | 163.030672 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.000000 | 162.861905 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 313 | 0.062600 | 0.000000 | 162.600738 | 0.000000 | 0.937400 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 313 | 0.062600 | 1.732051 | 163.003067 | 0.009585 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 0.000000 | 162.904880 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 312 | 0.062400 | 1.000000 | 162.397660 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 312 | 0.062400 | 0.000000 | 162.911019 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 312 | 0.062400 | 1.000000 | 163.251340 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 312 | 0.062400 | 3.162278 | 162.941707 | 0.012821 | 0.938400 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 626 | 0.125200 | 2.645751 | 153.052279 | 0.007987 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 2.000000 | 162.674522 | 0.012780 | 0.938200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 626 | 0.125200 | 12.369317 | 156.316986 | 0.164537 | 0.895400 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.000000 | 162.861905 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 626 | 0.125200 | 1.000000 | 152.725243 | 0.001597 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 1 | [6, 7] | 2 | 626 | 0.125200 | 3.605551 | 153.548038 | 0.017572 | 0.877000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 0.000000 | 162.904880 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | True | 1 | [8, 9] | 2 | 624 | 0.124800 | 1.414214 | 152.617168 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | True | 1 | [10, 11] | 2 | 624 | 0.124800 | 1.414214 | 153.166576 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | True | 1 | [12, 13] | 2 | 624 | 0.124800 | 1.414214 | 153.453576 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | True | 1 | [14, 15] | 2 | 624 | 0.124800 | 4.123106 | 152.515573 | 0.014423 | 0.875800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 2.645751 | 153.052279 | 0.007987 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 2.000000 | 162.674522 | 0.012780 | 0.938200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 5.477226 | 133.281657 | 0.023962 | 0.752000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.000000 | 162.861905 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 626 | 0.125200 | 1.000000 | 152.725243 | 0.001597 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 1 | [4, 5, 6, 7] | 4 | 1252 | 0.250400 | 6.633250 | 134.014925 | 0.030351 | 0.752400 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 0.000000 | 162.904880 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [8, 9] | 2 | 624 | 0.124800 | 1.414214 | 152.617168 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | True | 1 | [8, 9, 10, 11] | 4 | 1248 | 0.249600 | 9.055385 | 134.171532 | 0.038462 | 0.757600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 13 | False | 0 | [12, 13] | 2 | 624 | 0.124800 | 1.414214 | 153.453576 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 15 | True | 1 | [12, 13, 14, 15] | 4 | 1248 | 0.249600 | 8.366600 | 133.947751 | 0.038462 | 0.756000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 2.645751 | 153.052279 | 0.007987 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 2.000000 | 162.674522 | 0.012780 | 0.938200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 5.477226 | 133.281657 | 0.023962 | 0.752000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.000000 | 162.861905 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [4, 5] | 2 | 626 | 0.125200 | 1.000000 | 152.725243 | 0.001597 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 16.431677 | 97.560238 | 0.086262 | 0.520800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 0.000000 | 162.904880 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [8, 9] | 2 | 624 | 0.124800 | 1.414214 | 152.617168 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 1248 | 0.249600 | 9.055385 | 134.171532 | 0.038462 | 0.757600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 13 | False | 0 | [12, 13] | 2 | 624 | 0.124800 | 1.414214 | 153.453576 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 15 | True | 1 | [8, 9, 10, 11, 12, 13, 14, 15] | 8 | 2496 | 0.499200 | 93.348808 | 172.661519 | 1.000801 | 0.999600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 313 | 0.062600 | 1.414214 | 162.944776 | 0.006390 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 626 | 0.125200 | 2.645751 | 153.052279 | 0.007987 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [2] | 1 | 313 | 0.062600 | 2.000000 | 162.674522 | 0.012780 | 0.938200 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1252 | 0.250400 | 5.477226 | 133.281657 | 0.023962 | 0.752000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | False | 0 | [4] | 1 | 313 | 0.062600 | 1.000000 | 162.861905 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [4, 5] | 2 | 626 | 0.125200 | 1.000000 | 152.725243 | 0.001597 | 0.875000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 313 | 0.062600 | 1.000000 | 163.009202 | 0.003195 | 0.937600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 2504 | 0.500800 | 16.431677 | 97.560238 | 0.086262 | 0.520800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 312 | 0.062400 | 0.000000 | 162.904880 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [8, 9] | 2 | 624 | 0.124800 | 1.414214 | 152.617168 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 312 | 0.062400 | 1.000000 | 162.871115 | 0.003205 | 0.937800 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 1248 | 0.249600 | 9.055385 | 134.171532 | 0.038462 | 0.757600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 12 | False | 0 | [12] | 1 | 312 | 0.062400 | 0.000000 | 162.831201 | 0.000000 | 0.937600 | True | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 13 | False | 0 | [12, 13] | 2 | 624 | 0.124800 | 1.414214 | 153.453576 | 0.003205 | 0.875600 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 14 | False | 0 | [14] | 1 | 312 | 0.062400 | 1.414214 | 162.376107 | 0.006410 | 0.938000 | False | False |
| tree | 16 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 15 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 5000 | 1.000000 | 56.231664 | 56.231664 | 0.272800 | 0.272800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 157 | 0.031400 | 0.000000 | 167.693172 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 157 | 0.031400 | 1.000000 | 167.618615 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 157 | 0.031400 | 1.000000 | 167.499254 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 157 | 0.031400 | 1.000000 | 167.624581 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 156 | 0.031200 | 0.000000 | 167.821334 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 156 | 0.031200 | 0.000000 | 167.845167 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 13 | False | 0 | [13] | 1 | 156 | 0.031200 | 0.000000 | 167.839209 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 15 | False | 0 | [15] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 17 | False | 0 | [17] | 1 | 156 | 0.031200 | 1.000000 | 167.788557 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 19 | False | 0 | [19] | 1 | 156 | 0.031200 | 1.000000 | 167.693172 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 21 | False | 0 | [21] | 1 | 156 | 0.031200 | 0.000000 | 167.666335 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 23 | False | 0 | [23] | 1 | 156 | 0.031200 | 0.000000 | 167.773657 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 25 | False | 0 | [25] | 1 | 156 | 0.031200 | 0.000000 | 167.588782 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 27 | False | 0 | [27] | 1 | 156 | 0.031200 | 1.000000 | 168.133875 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 29 | False | 0 | [29] | 1 | 156 | 0.031200 | 1.000000 | 167.764716 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 31 | False | 0 | [31] | 1 | 156 | 0.031200 | 1.000000 | 167.687209 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 314 | 0.062800 | 1.414214 | 162.825059 | 0.006369 | 0.937200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 314 | 0.062800 | 1.414214 | 162.769776 | 0.006369 | 0.937600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 314 | 0.062800 | 4.582576 | 163.226836 | 0.066879 | 0.941400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 1 | [6, 7] | 2 | 314 | 0.062800 | 1.414214 | 162.923295 | 0.006369 | 0.937600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | True | 1 | [8, 9] | 2 | 312 | 0.062400 | 1.732051 | 163.012269 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | True | 1 | [10, 11] | 2 | 312 | 0.062400 | 1.000000 | 162.649931 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 13 | True | 1 | [12, 13] | 2 | 312 | 0.062400 | 1.414214 | 163.144108 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 15 | True | 1 | [14, 15] | 2 | 312 | 0.062400 | 2.000000 | 163.052139 | 0.012821 | 0.938400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 17 | True | 1 | [16, 17] | 2 | 312 | 0.062400 | 1.414214 | 162.953981 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 19 | True | 1 | [18, 19] | 2 | 312 | 0.062400 | 1.000000 | 162.409975 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 21 | True | 1 | [20, 21] | 2 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 23 | True | 1 | [22, 23] | 2 | 312 | 0.062400 | 2.236068 | 162.987730 | 0.009615 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 25 | True | 1 | [24, 25] | 2 | 312 | 0.062400 | 1.000000 | 162.858835 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 27 | True | 1 | [26, 27] | 2 | 312 | 0.062400 | 2.000000 | 163.364623 | 0.012821 | 0.938400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 29 | True | 1 | [28, 29] | 2 | 312 | 0.062400 | 1.732051 | 162.409975 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 31 | True | 1 | [30, 31] | 2 | 312 | 0.062400 | 1.414214 | 162.800491 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.414214 | 162.825059 | 0.006369 | 0.937200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 7.000000 | 154.411787 | 0.065287 | 0.882200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 314 | 0.062800 | 4.582576 | 163.226836 | 0.066879 | 0.941400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 1 | [4, 5, 6, 7] | 4 | 628 | 0.125600 | 3.000000 | 153.065346 | 0.014331 | 0.875800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [8, 9] | 2 | 312 | 0.062400 | 1.732051 | 163.012269 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | True | 1 | [8, 9, 10, 11] | 4 | 624 | 0.124800 | 2.000000 | 152.931357 | 0.006410 | 0.876000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 13 | False | 0 | [12, 13] | 2 | 312 | 0.062400 | 1.414214 | 163.144108 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 15 | True | 1 | [12, 13, 14, 15] | 4 | 624 | 0.124800 | 13.228757 | 157.114608 | 0.216346 | 0.899400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 17 | False | 0 | [16, 17] | 2 | 312 | 0.062400 | 1.414214 | 162.953981 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 19 | True | 1 | [16, 17, 18, 19] | 4 | 624 | 0.124800 | 3.741657 | 152.879037 | 0.022436 | 0.877600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 21 | False | 0 | [20, 21] | 2 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 23 | True | 1 | [20, 21, 22, 23] | 4 | 624 | 0.124800 | 6.082763 | 154.184954 | 0.056090 | 0.881800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 25 | False | 0 | [24, 25] | 2 | 312 | 0.062400 | 1.000000 | 162.858835 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 27 | True | 1 | [24, 25, 26, 27] | 4 | 624 | 0.124800 | 3.000000 | 153.645696 | 0.014423 | 0.876600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 29 | False | 0 | [28, 29] | 2 | 312 | 0.062400 | 1.732051 | 162.409975 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 31 | True | 1 | [28, 29, 30, 31] | 4 | 624 | 0.124800 | 6.403124 | 153.306882 | 0.052885 | 0.881000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.414214 | 162.825059 | 0.006369 | 0.937200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 7.000000 | 154.411787 | 0.065287 | 0.882200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [4, 5] | 2 | 314 | 0.062800 | 4.582576 | 163.226836 | 0.066879 | 0.941400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 8.306624 | 134.324235 | 0.048567 | 0.758200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [8, 9] | 2 | 312 | 0.062400 | 1.732051 | 163.012269 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 624 | 0.124800 | 2.000000 | 152.931357 | 0.006410 | 0.876000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 13 | False | 0 | [12, 13] | 2 | 312 | 0.062400 | 1.414214 | 163.144108 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 15 | True | 1 | [8, 9, 10, 11, 12, 13, 14, 15] | 8 | 1248 | 0.249600 | 14.594520 | 137.291660 | 0.103365 | 0.772600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 17 | False | 0 | [16, 17] | 2 | 312 | 0.062400 | 1.414214 | 162.953981 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 19 | False | 0 | [16, 17, 18, 19] | 4 | 624 | 0.124800 | 3.741657 | 152.879037 | 0.022436 | 0.877600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 21 | False | 0 | [20, 21] | 2 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 23 | True | 1 | [16, 17, 18, 19, 20, 21, 22, 23] | 8 | 1248 | 0.249600 | 22.226111 | 142.028166 | 0.270833 | 0.804400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 25 | False | 0 | [24, 25] | 2 | 312 | 0.062400 | 1.000000 | 162.858835 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 27 | False | 0 | [24, 25, 26, 27] | 4 | 624 | 0.124800 | 3.000000 | 153.645696 | 0.014423 | 0.876600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 29 | False | 0 | [28, 29] | 2 | 312 | 0.062400 | 1.732051 | 162.409975 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 31 | True | 1 | [24, 25, 26, 27, 28, 29, 30, 31] | 8 | 1248 | 0.249600 | 10.583005 | 134.141716 | 0.068910 | 0.757200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.414214 | 162.825059 | 0.006369 | 0.937200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 7.000000 | 154.411787 | 0.065287 | 0.882200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [4, 5] | 2 | 314 | 0.062800 | 4.582576 | 163.226836 | 0.066879 | 0.941400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 8.306624 | 134.324235 | 0.048567 | 0.758200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [8, 9] | 2 | 312 | 0.062400 | 1.732051 | 163.012269 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 624 | 0.124800 | 2.000000 | 152.931357 | 0.006410 | 0.876000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 13 | False | 0 | [12, 13] | 2 | 312 | 0.062400 | 1.414214 | 163.144108 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 15 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 17.832555 | 96.374270 | 0.106230 | 0.513200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 17 | False | 0 | [16, 17] | 2 | 312 | 0.062400 | 1.414214 | 162.953981 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 19 | False | 0 | [16, 17, 18, 19] | 4 | 624 | 0.124800 | 3.741657 | 152.879037 | 0.022436 | 0.877600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 21 | False | 0 | [20, 21] | 2 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 23 | False | 0 | [16, 17, 18, 19, 20, 21, 22, 23] | 8 | 1248 | 0.249600 | 22.226111 | 142.028166 | 0.270833 | 0.804400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 25 | False | 0 | [24, 25] | 2 | 312 | 0.062400 | 1.000000 | 162.858835 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 27 | False | 0 | [24, 25, 26, 27] | 4 | 624 | 0.124800 | 3.000000 | 153.645696 | 0.014423 | 0.876600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 29 | False | 0 | [28, 29] | 2 | 312 | 0.062400 | 1.732051 | 162.409975 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 31 | True | 1 | [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31] | 16 | 2496 | 0.499200 | 93.348808 | 172.661519 | 1.000801 | 0.999600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 157 | 0.031400 | 0.000000 | 167.860061 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 314 | 0.062800 | 1.414214 | 162.825059 | 0.006369 | 0.937200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [2] | 1 | 157 | 0.031400 | 0.000000 | 167.830271 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 628 | 0.125600 | 7.000000 | 154.411787 | 0.065287 | 0.882200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [4] | 1 | 157 | 0.031400 | 0.000000 | 167.782597 | 0.000000 | 0.968600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | False | 0 | [4, 5] | 2 | 314 | 0.062800 | 4.582576 | 163.226836 | 0.066879 | 0.941400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 157 | 0.031400 | 1.000000 | 167.970235 | 0.006369 | 0.968800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 1256 | 0.251200 | 8.306624 | 134.324235 | 0.048567 | 0.758200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 8 | False | 0 | [8] | 1 | 156 | 0.031200 | 1.000000 | 167.800477 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 9 | False | 0 | [8, 9] | 2 | 312 | 0.062400 | 1.732051 | 163.012269 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 10 | False | 0 | [10] | 1 | 156 | 0.031200 | 0.000000 | 167.487313 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 624 | 0.124800 | 2.000000 | 152.931357 | 0.006410 | 0.876000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 12 | False | 0 | [12] | 1 | 156 | 0.031200 | 1.414214 | 167.988095 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 13 | False | 0 | [12, 13] | 2 | 312 | 0.062400 | 1.414214 | 163.144108 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 14 | False | 0 | [14] | 1 | 156 | 0.031200 | 1.414214 | 167.714042 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 15 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] | 16 | 2504 | 0.500800 | 17.832555 | 96.374270 | 0.106230 | 0.513200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 16 | False | 0 | [16] | 1 | 156 | 0.031200 | 1.000000 | 167.830271 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 17 | False | 0 | [16, 17] | 2 | 312 | 0.062400 | 1.414214 | 162.953981 | 0.006410 | 0.938000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 18 | False | 0 | [18] | 1 | 156 | 0.031200 | 0.000000 | 167.391756 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 19 | False | 0 | [16, 17, 18, 19] | 4 | 624 | 0.124800 | 3.741657 | 152.879037 | 0.022436 | 0.877600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 20 | False | 0 | [20] | 1 | 156 | 0.031200 | 0.000000 | 167.833251 | 0.000000 | 0.968800 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 21 | False | 0 | [20, 21] | 2 | 312 | 0.062400 | 0.000000 | 162.843483 | 0.000000 | 0.937600 | True | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 22 | False | 0 | [22] | 1 | 156 | 0.031200 | 1.000000 | 167.740872 | 0.006410 | 0.968600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 23 | False | 0 | [16, 17, 18, 19, 20, 21, 22, 23] | 8 | 1248 | 0.249600 | 22.226111 | 142.028166 | 0.270833 | 0.804400 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 24 | False | 0 | [24] | 1 | 156 | 0.031200 | 1.000000 | 167.913668 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 25 | False | 0 | [24, 25] | 2 | 312 | 0.062400 | 1.000000 | 162.858835 | 0.003205 | 0.937800 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 26 | False | 0 | [26] | 1 | 156 | 0.031200 | 1.414214 | 167.827292 | 0.012821 | 0.969200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 27 | False | 0 | [24, 25, 26, 27] | 4 | 624 | 0.124800 | 3.000000 | 153.645696 | 0.014423 | 0.876600 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 28 | False | 0 | [28] | 1 | 156 | 0.031200 | 1.000000 | 167.251308 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 29 | False | 0 | [28, 29] | 2 | 312 | 0.062400 | 1.732051 | 162.409975 | 0.009615 | 0.938200 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 30 | False | 0 | [30] | 1 | 156 | 0.031200 | 1.000000 | 167.782597 | 0.006410 | 0.969000 | False | False |
| tree | 32 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 31 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31] | 32 | 5000 | 1.000000 | 54.543561 | 54.543561 | 0.265000 | 0.265000 | False | False |
