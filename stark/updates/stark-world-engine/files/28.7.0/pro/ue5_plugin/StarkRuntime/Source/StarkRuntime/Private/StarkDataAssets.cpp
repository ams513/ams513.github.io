// Stark World Engine Runtime - data assets (see StarkDataAssets.h).
// FJsonObjectConverter::JsonObjectStringToUStruct:
//   https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/JsonUtilities/FJsonObjectConverter/JsonObjectStringToUStruct
#include "StarkDataAssets.h"
#include "JsonObjectConverter.h"

bool UStarkItemAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Item); }
bool UStarkEnemyAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Enemy); }
bool UStarkNpcAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Npc); }
bool UStarkQuestAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Quest); }
bool UStarkDialogueAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Dialogue); }
bool UStarkLevelAsset::ImportJson(const FString& Json) { return FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Level); }

bool UStarkGameData::ImportHeaderJson(const FString& Json)
{
	FStarkGameDef Def;
	if (!FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Def))
	{
		return false;
	}
	Title = Def.Title;
	Author = Def.Author;
	Story = Def.Story;
	SaveKey = Def.SaveKey;
	Minors = Def.Minors;
	Rules = Def.Rules;
	return true;
}

FStarkGameDef UStarkGameData::BuildGameDef() const
{
	FStarkGameDef Def;
	Def.Title = Title;
	Def.Author = Author;
	Def.Story = Story;
	Def.SaveKey = SaveKey;
	Def.Minors = Minors;
	Def.Rules = Rules;
	for (const UStarkItemAsset* A : Items) { if (A) { Def.Items.Add(A->Item); } }
	for (const UStarkEnemyAsset* A : Enemies) { if (A) { Def.Enemies.Add(A->Enemy); } }
	for (const UStarkQuestAsset* A : Quests) { if (A) { Def.Quests.Add(A->Quest); } }
	for (const UStarkDialogueAsset* A : Dialogues) { if (A) { Def.Dialogues.Add(A->Dialogue); } }
	for (const UStarkNpcAsset* A : Npcs) { if (A) { Def.Npcs.Add(A->Npc); } }
	for (const UStarkLevelAsset* A : Levels) { if (A) { Def.Levels.Add(A->Level); } }
	Def.Levels.Sort([](const FStarkLevelDef& L, const FStarkLevelDef& R) { return L.Index < R.Index; });
	return Def;
}
