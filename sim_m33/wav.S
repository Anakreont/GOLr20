 .section .rodata
 .balign 4
 .global wav_start
wav_start:
 .incbin WAVFILE
 .global wav_end
wav_end:
