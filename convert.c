#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>

void remove_extension(char *filename, char *base) {
    char *dot = strrchr(filename, '.');
    if (dot) {
        size_t len = dot - filename;
        strncpy(base, filename, len);
        base[len] = '\0';
    } else {
        strcpy(base, filename);
    }
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <fichier_mp4>\n", argv[0]);
        return 1;
    }

    char *input_path = argv[1];
    char *filename = basename(input_path);
    char base_name[256];
    char output_mp3[512];
    char output_gif[512];
    char command[1024];
    int status;

    // Extraire le nom de base sans extension
    remove_extension(filename, base_name);

    // Chemins de sortie
    snprintf(output_mp3, sizeof(output_mp3), "core/%s.mp3", base_name);
    snprintf(output_gif, sizeof(output_gif), "core/%s.gif", base_name);

    printf("📹 Fichier d'entrée : %s\n", input_path);
    printf("🎵 Sortie MP3 : %s\n", output_mp3);
    printf("🎨 Sortie GIF : %s\n", output_gif);

    // === Conversion MP4 -> MP3 ===
    printf("\n🎵 Extraction de l'audio en MP3...\n");
    snprintf(command, sizeof(command),
             "ffmpeg -i \"%s\" -vn -acodec libmp3lame -q:a 2 \"%s\" -y",
             input_path, output_mp3);
    
    status = system(command);
    if (status != 0) {
        fprintf(stderr, "❌ Erreur lors de la conversion MP3\n");
        return 1;
    }
    printf("✅ MP3 créé avec succès\n");

    // === Conversion MP4 -> GIF (10 premières secondes) ===
    printf("\n🎨 Création du GIF (10 premières secondes)...\n");
    
    // Étape 1 : Extraire les 10 premières secondes et créer une palette
    char palette_path[512];
    snprintf(palette_path, sizeof(palette_path), "core/%s_palette.png", base_name);
    
    // GIF CARRÉ 250x250 avec crop centré
    snprintf(command, sizeof(command),
             "ffmpeg -i \"%s\" -t 10 -vf \"fps=10,scale=250:250:force_original_aspect_ratio=increase,crop=250:250,palettegen\" \"%s\" -y",
             input_path, palette_path);
    
    status = system(command);
    if (status != 0) {
        fprintf(stderr, "❌ Erreur lors de la création de la palette\n");
        return 1;
    }
    
    // Étape 2 : Créer le GIF carré 250x250 avec la palette
    snprintf(command, sizeof(command),
             "ffmpeg -i \"%s\" -i \"%s\" -t 30 -lavfi \"fps=10,scale=250:250:force_original_aspect_ratio=increase,crop=250:250[x];[x][1:v]paletteuse\" \"%s\" -y",
             input_path, palette_path, output_gif);
    
    status = system(command);
    if (status != 0) {
        fprintf(stderr, "❌ Erreur lors de la création du GIF\n");
        return 1;
    }
    
    // Supprimer la palette temporaire
    remove(palette_path);
    
    printf("✅ GIF créé avec succès (10 premières secondes, 250x250)\n");

    printf("\n🎉 Conversion terminée !\n");
    printf("   MP3 : %s\n", output_mp3);
    printf("   GIF : %s\n", output_gif);

    return 0;
}