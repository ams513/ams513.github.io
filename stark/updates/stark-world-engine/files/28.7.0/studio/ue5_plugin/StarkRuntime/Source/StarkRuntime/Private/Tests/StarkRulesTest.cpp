// Stark World Engine Runtime - automation test of the rules (no world needed):
//   UnrealEditor-Cmd.exe <project> -ExecCmds="Automation RunTests StarkWorldEngine.Runtime;Quit" -unattended -nullrhi -nosplash
// Automation tests: https://dev.epicgames.com/documentation/en-us/unreal-engine/write-cplusplus-tests-in-unreal-engine
#include "Misc/AutomationTest.h"
#include "StarkRules.h"
#include "JsonObjectConverter.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStarkRulesTest, "StarkWorldEngine.Runtime.Rules",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FStarkRulesTest::RunTest(const FString& Parameters)
{
	FStarkGameDef Def;
	Def.Rules.PlayerHp = 6;
	FStarkItemDef Crystal;
	Crystal.Id = TEXT("crystal");
	Crystal.Name = TEXT("Glow Crystal");
	Crystal.Kind = TEXT("quest");
	Def.Items.Add(Crystal);
	FStarkItemDef Blade;
	Blade.Id = TEXT("iron_blade");
	Blade.Name = TEXT("Iron Blade");
	Blade.Kind = TEXT("equip");
	Blade.Slot = TEXT("weapon");
	Blade.Atk = 2;
	Def.Items.Add(Blade);
	FStarkQuestDef Q;
	Q.Id = TEXT("q1");
	Q.Title = TEXT("Spore Harvest");
	Q.Giver = TEXT("moss");
	FStarkQuestStep Collect;
	Collect.Type = TEXT("collect");
	Collect.Item = TEXT("crystal");
	Collect.Count = 2;
	Collect.Consume = true;
	FStarkQuestStep Talk;
	Talk.Type = TEXT("talk");
	Talk.Npc = TEXT("moss");
	Q.Steps = { Collect, Talk };
	Q.Reward.Xp = 60;
	Q.Reward.Items = { TEXT("iron_blade") };
	Q.Final = true;
	Def.Quests.Add(Q);
	FStarkDialogueDef D;
	D.Id = TEXT("moss");
	D.Start = TEXT("hi");
	FStarkDialogueNode Hi;
	Hi.Id = TEXT("hi");
	Hi.Text = TEXT("Gather the crystals?");
	FStarkChoice Yes;
	Yes.Text = TEXT("Yes");
	Yes.Action.Start = TEXT("q1");
	FStarkChoice No;
	No.Text = TEXT("Not now");
	No.End = true;
	Hi.Choices = { Yes, No };
	D.Nodes.Add(Hi);
	Def.Dialogues.Add(D);
	FStarkLevelDef L;
	L.Index = 0;
	L.Name = TEXT("Test");
	L.Mode = TEXT("3d");
	Def.Levels.Add(L);

	UStarkRules* R = NewObject<UStarkRules>();
	R->Setup(Def);
	R->NewGame();
	R->Talk(TEXT("moss"), TEXT("moss"), TEXT("Elder Moss"), FString());
	TestTrue(TEXT("dialogue opens"), R->bDialogueOpen);
	TestEqual(TEXT("two answers"), R->VisibleChoices.Num(), 2);
	R->Choose(0);
	TestEqual(TEXT("quest started"), R->QuestState(TEXT("q1")), FString(TEXT("active")));
	R->Give(TEXT("crystal"), 1, true);
	R->Give(TEXT("crystal"), 1, true);
	TestEqual(TEXT("collect step done and consumed"), R->Count(TEXT("crystal")), 0);
	FStarkEvent E;
	E.Npc = TEXT("moss");
	R->Event(TEXT("talk"), E);
	TestEqual(TEXT("quest done"), R->QuestState(TEXT("q1")), FString(TEXT("done")));
	TestTrue(TEXT("reward equipped"), R->Equipped.Contains(TEXT("weapon")));
	TestEqual(TEXT("attack with blade"), R->Stats().Atk, 1 + (R->Lvl - 1) / 2 + 2);
	TestTrue(TEXT("final quest wins"), R->bWon);

	// the exported game, when this project has one
	FString Json;
	if (FFileHelper::LoadFileToString(Json, *(FPaths::ProjectContentDir() / TEXT("Stark/Data/stark_game_ue.json"))))
	{
		FStarkGameDef Game;
		TestTrue(TEXT("stark_game_ue.json parses"), FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Game));
		TestTrue(TEXT("game has levels"), Game.Levels.Num() > 0);
		UStarkRules* G = NewObject<UStarkRules>();
		G->Setup(Game);
		G->NewGame();
		G->StartLevelQuests(0);
		for (const FStarkQuestDef& Gq : Game.Quests)
		{
			TestNotNull(TEXT("quest findable"), G->FindQuest(Gq.Id));
		}
	}
	return true;
}

#endif
